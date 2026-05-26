from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from cruise_email_dashboard.database.db import SessionLocal
from cruise_email_dashboard.database.models import EmailLog
from cruise_email_dashboard.services.notifications import broker

router = APIRouter(tags=["stream"])


@router.get("/stream")
async def stream(request: Request):
    """Server-Sent Events endpoint for lightweight dashboard push updates.

    SSE works well here because the browser only needs one-way updates from the server:
    "new emails arrived" and "refresh your counters". Each browser connection gets its
    own asyncio queue, and the notification broker fans out events to every queue.

    The loop sends a heartbeat comment periodically so proxies and browsers do not treat
    the connection as idle and close it. When the client disconnects, we remove the
    queue from the broker to avoid leaking memory.
    """

    def _unread_count() -> int:
        db = SessionLocal()
        try:
            return db.query(EmailLog).filter(EmailLog.is_new.is_(True)).count()
        finally:
            db.close()

    async def event_generator():
        queue = await broker.subscribe()
        try:
            unread_count = _unread_count()
            yield f"event: unread_count\ndata: {{\"count\": {unread_count}}}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=15)
                    yield message
                    unread_count = _unread_count()
                    yield f"event: unread_count\ndata: {{\"count\": {unread_count}}}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            broker.unsubscribe(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
