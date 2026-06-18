from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextlib import suppress

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from cruise_email_dashboard.database.db import SessionLocal, init_db
from cruise_email_dashboard.routers import admin, analytics, auth, inbox, logs, map as map_router, presence, stream
from cruise_email_dashboard.services.email_poller import poll_forever
from cruise_email_dashboard.services.notifications import broker
from cruise_email_dashboard.services.presence import cleanup_stale_presence, scheduled_cleanup_cutoff
from cruise_email_dashboard.settings import settings


def cleanup_presence_job() -> None:
    db = SessionLocal()
    try:
        stale_email_ids = cleanup_stale_presence(db, older_than=scheduled_cleanup_cutoff())
        for email_id in stale_email_ids:
            broker.publish_nowait("presence_changed", {"email_id": email_id})
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = AsyncIOScheduler()
    app.state.scheduler = scheduler
    scheduler.add_job(cleanup_presence_job, "interval", minutes=5, id="presence_cleanup", replace_existing=True)
    scheduler.start()
    poller = asyncio.create_task(poll_forever(SessionLocal))
    try:
        yield
    finally:
        poller.cancel()
        with suppress(asyncio.CancelledError):
            await poller
        scheduler.shutdown(wait=False)
        app.state.scheduler = None


app = FastAPI(title="Cruise Email Dashboard", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="cruise_dashboard_session",
    https_only=True,
    same_site="lax",
    max_age=604800,
)
app.mount("/static", StaticFiles(directory="cruise_email_dashboard/static"), name="static")

app.include_router(auth.router)
app.include_router(analytics.router)
app.include_router(inbox.router)
app.include_router(logs.router)
app.include_router(map_router.router)
app.include_router(admin.router)
app.include_router(admin.hotel_management_router)
app.include_router(presence.router)
app.include_router(stream.router)


@app.get("/health")
def healthcheck():
    return {"status": "ok"}


@app.get("/dashboard")
def dashboard_redirect():
    return RedirectResponse(url="/", status_code=303)
