from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from cruise_email_dashboard.database.db import get_db
from cruise_email_dashboard.database.models import EmailLog, User, UserPresence
from cruise_email_dashboard.dependencies import get_current_user
from cruise_email_dashboard.services.csrf import validate_csrf
from cruise_email_dashboard.services.notifications import broker
from cruise_email_dashboard.services.presence import (
    ACTIVE_WINDOW_SECONDS,
    active_cutoff,
    get_active_presence_batch,
    get_active_presence_for_email,
    utc_now_naive,
)

router = APIRouter(prefix="/presence", tags=["presence"], dependencies=[Depends(validate_csrf)])


class HeartbeatPayload(BaseModel):
    email_log_id: int
    session_id: str


class LeavePayload(BaseModel):
    email_log_id: int
    session_id: str


@router.post("/heartbeat")
def heartbeat(
    payload: HeartbeatPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    cutoff = active_cutoff()
    stale_email_ids = [
        email_id
        for (email_id,) in db.query(UserPresence.email_log_id).filter(UserPresence.last_seen < cutoff).distinct().all()
    ]
    if stale_email_ids:
        db.query(UserPresence).filter(UserPresence.last_seen < cutoff).delete(synchronize_session=False)

    email = db.query(EmailLog.id).filter(EmailLog.id == payload.email_log_id).first()
    if not email:
        db.commit()
        return {"ok": False, "active_window_seconds": ACTIVE_WINDOW_SECONDS}

    row = (
        db.query(UserPresence)
        .filter(UserPresence.user_id == user.id, UserPresence.session_id == payload.session_id)
        .first()
    )
    should_publish = False
    if row:
        should_publish = row.email_log_id != payload.email_log_id or row.last_seen < cutoff
        row.email_log_id = payload.email_log_id
        row.last_seen = utc_now_naive()
    else:
        should_publish = True
        db.add(
            UserPresence(
                user_id=user.id,
                email_log_id=payload.email_log_id,
                last_seen=utc_now_naive(),
                session_id=payload.session_id,
            )
        )

    db.commit()
    for stale_email_id in stale_email_ids:
        if stale_email_id != payload.email_log_id:
            broker.publish_nowait("presence_changed", {"email_id": stale_email_id})
    if should_publish:
        broker.publish_nowait("presence_changed", {"email_id": payload.email_log_id})
    return {"ok": True, "active_window_seconds": ACTIVE_WINDOW_SECONDS}


@router.post("/leave")
def leave(
    payload: LeavePayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    deleted = (
        db.query(UserPresence)
        .filter(UserPresence.user_id == user.id, UserPresence.session_id == payload.session_id)
        .delete(synchronize_session=False)
    )
    db.commit()
    if deleted:
        broker.publish_nowait("presence_changed", {"email_id": payload.email_log_id})
    return {"ok": True}


@router.get("/active/{email_log_id}")
def active_presence(
    email_log_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return get_active_presence_for_email(db, email_log_id, user.id)


@router.get("/batch")
def batch_presence(
    ids: str = Query(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    email_ids: list[int] = []
    for raw_value in ids.split(","):
        raw_value = raw_value.strip()
        if raw_value.isdigit():
            email_ids.append(int(raw_value))
    unique_ids = list(dict.fromkeys(email_ids))
    return get_active_presence_batch(db, unique_ids, user.id)
