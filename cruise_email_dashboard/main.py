from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from cruise_email_dashboard.database.db import SessionLocal, init_db
from cruise_email_dashboard.routers import admin, analytics, auth, inbox, logs, map as map_router, stream
from cruise_email_dashboard.services.email_poller import poll_forever
from cruise_email_dashboard.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    poller = asyncio.create_task(poll_forever(SessionLocal))
    yield
    poller.cancel()


app = FastAPI(title="Cruise Email Dashboard", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, session_cookie="cruise_dashboard_session")
app.mount("/static", StaticFiles(directory="cruise_email_dashboard/static"), name="static")

app.include_router(auth.router)
app.include_router(analytics.router)
app.include_router(inbox.router)
app.include_router(logs.router)
app.include_router(map_router.router)
app.include_router(admin.router)
app.include_router(stream.router)


@app.get("/health")
def healthcheck():
    return {"status": "ok"}


@app.get("/dashboard")
def dashboard_redirect():
    return RedirectResponse(url="/", status_code=303)
