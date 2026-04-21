from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload

from cruise_email_dashboard.database.db import get_db
from cruise_email_dashboard.database.models import EmailLog, User
from cruise_email_dashboard.dependencies import get_current_user, template_context, templates

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("")
def logs_page(request: Request, q: str = "", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = db.query(EmailLog).options(joinedload(EmailLog.detected_hotel), joinedload(EmailLog.assigned_bus_stop))
    if q:
        like = f"%{q}%"
        query = query.filter(
            EmailLog.sender_email.ilike(like)
            | EmailLog.subject.ilike(like)
            | EmailLog.body_snippet.ilike(like)
            | EmailLog.detected_language.ilike(like)
            | EmailLog.booking_number.ilike(like)
        )
    rows = query.order_by(EmailLog.received_at.desc()).all()
    return templates.TemplateResponse("logs.html", template_context(request, user=user, rows=rows, q=q))


@router.get("/export")
def export_logs(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    rows = db.query(EmailLog).options(joinedload(EmailLog.detected_hotel), joinedload(EmailLog.assigned_bus_stop)).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["timestamp", "booking_number", "sender", "hotel", "bus_stop", "language", "status", "reply_preview"])
    for row in rows:
        writer.writerow(
            [
                row.received_at.isoformat(),
                row.booking_number,
                row.sender_email,
                row.detected_hotel.name if row.detected_hotel else "",
                row.assigned_bus_stop.name if row.assigned_bus_stop else "",
                row.detected_language,
                row.status.value,
                row.draft_reply[:120],
            ]
        )
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=emails_log.csv"},
    )
