from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from cruise_email_dashboard.database.db import get_db
from cruise_email_dashboard.database.models import EmailLog, EmailStatus, User
from cruise_email_dashboard.dependencies import get_current_user, template_context, templates

router = APIRouter()


@router.get("/")
def home(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    total_today = db.query(func.count(EmailLog.id)).filter(EmailLog.received_at >= today_start).scalar() or 0
    sent_today = (
        db.query(func.count(EmailLog.id))
        .filter(EmailLog.status == EmailStatus.sent, EmailLog.sent_at.is_not(None), EmailLog.sent_at >= today_start)
        .scalar()
        or 0
    )
    flagged = db.query(func.count(EmailLog.id)).filter(EmailLog.status == EmailStatus.flagged).scalar() or 0
    cancelled = db.query(func.count(EmailLog.id)).filter(EmailLog.status == EmailStatus.cancelled).scalar() or 0

    chart_days: list[str] = []
    sent_series: list[int] = []
    flagged_series: list[int] = []
    manual_series: list[int] = []
    cancelled_series: list[int] = []
    for offset in range(6, -1, -1):
        day = (now - timedelta(days=offset)).date()
        next_day = day + timedelta(days=1)
        chart_days.append(day.strftime("%b %d"))
        sent_series.append(
            db.query(func.count(EmailLog.id))
            .filter(EmailLog.received_at >= day, EmailLog.received_at < next_day, EmailLog.status == EmailStatus.sent)
            .scalar()
            or 0
        )
        flagged_series.append(
            db.query(func.count(EmailLog.id))
            .filter(EmailLog.received_at >= day, EmailLog.received_at < next_day, EmailLog.status == EmailStatus.flagged)
            .scalar()
            or 0
        )
        manual_series.append(
            db.query(func.count(EmailLog.id))
            .filter(EmailLog.received_at >= day, EmailLog.received_at < next_day, EmailLog.status == EmailStatus.manual)
            .scalar()
            or 0
        )
        cancelled_series.append(
            db.query(func.count(EmailLog.id))
            .filter(EmailLog.received_at >= day, EmailLog.received_at < next_day, EmailLog.status == EmailStatus.cancelled)
            .scalar()
            or 0
        )

    language_rows = (
        db.query(EmailLog.detected_language, func.count(EmailLog.id))
        .group_by(EmailLog.detected_language)
        .order_by(func.count(EmailLog.id).desc())
        .all()
    )
    recent_activity = db.query(EmailLog).order_by(EmailLog.received_at.desc()).limit(10).all()

    return templates.TemplateResponse(
        "home.html",
        template_context(
            request,
            user=user,
            total_today=total_today,
            sent_today=sent_today,
            flagged=flagged,
            cancelled=cancelled,
            chart_days=chart_days,
            sent_series=sent_series,
            flagged_series=flagged_series,
            manual_series=manual_series,
            cancelled_series=cancelled_series,
            language_labels=[row[0] for row in language_rows],
            language_values=[row[1] for row in language_rows],
            recent_activity=recent_activity,
        ),
    )
