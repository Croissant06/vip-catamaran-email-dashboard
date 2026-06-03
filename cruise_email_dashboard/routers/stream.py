from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from cruise_email_dashboard.database.db import SessionLocal
from cruise_email_dashboard.database.models import EmailLog
from cruise_email_dashboard.services.notifications import broker

router = APIRouter(tags=["stream"])


async def _wait_for_disconnect(request: Request) -> None:
    while True:
        if await request.is_disconnected():
            return
        await asyncio.sleep(0.5)


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
        disconnect_task = asyncio.create_task(_wait_for_disconnect(request))
        queue_task: asyncio.Task[str] | None = asyncio.create_task(queue.get())
        try:
            unread_count = _unread_count()
            yield "retry: 5000\n\n"
            yield f"event: unread_count\ndata: {{\"count\": {unread_count}}}\n\n"
            while True:
                done, _ = await asyncio.wait(
                    {disconnect_task, queue_task},
                    timeout=15,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if disconnect_task in done:
                    break
                if queue_task in done:
                    message = queue_task.result()
                    queue_task = asyncio.create_task(queue.get())
                    yield message
                    unread_count = _unread_count()
                    yield f"event: unread_count\ndata: {{\"count\": {unread_count}}}\n\n"
                else:
                    yield ": keep-alive\n\n"
        finally:
            disconnect_task.cancel()
            if queue_task is not None:
                queue_task.cancel()
            broker.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
