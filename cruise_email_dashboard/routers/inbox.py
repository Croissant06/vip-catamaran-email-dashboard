from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session, joinedload

from cruise_email_dashboard.database.db import get_db
from cruise_email_dashboard.database.models import BusStop, EmailLog, EmailStatus, Hotel, User
from cruise_email_dashboard.dependencies import get_current_user, template_context, templates
from cruise_email_dashboard.services.mailer import send_reply
from cruise_email_dashboard.services.reply_generator import MISSING_PICKUP_TIME_PLACEHOLDER, regenerate_email_draft
from cruise_email_dashboard.services.scheduler import resolve_pickup_schedule

router = APIRouter(prefix="/inbox", tags=["inbox"])


@router.get("")
def inbox_page(
    request: Request,
    status: str = Query(default=""),
    language: str = Query(default=""),
    start_date: str = Query(default=""),
    end_date: str = Query(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = db.query(EmailLog).options(joinedload(EmailLog.detected_hotel), joinedload(EmailLog.assigned_bus_stop))
    if status:
        query = query.filter(EmailLog.status == status)
    if language:
        query = query.filter(EmailLog.detected_language == language)
    if start_date:
        query = query.filter(EmailLog.received_at >= datetime.fromisoformat(start_date))
    if end_date:
        query = query.filter(EmailLog.received_at < datetime.fromisoformat(end_date + "T23:59:59"))

    emails = query.order_by(EmailLog.received_at.desc()).all()
    languages = [row[0] for row in db.query(EmailLog.detected_language).distinct().order_by(EmailLog.detected_language).all()]
    unread_count = db.query(EmailLog).filter(EmailLog.is_new.is_(True)).count()
    return templates.TemplateResponse(
        "inbox.html",
        template_context(
            request,
            user=user,
            emails=emails,
            unread_count=unread_count,
            languages=languages,
            filters={"status": status, "language": language, "start_date": start_date, "end_date": end_date},
        ),
    )


@router.get("/{email_id}")
def email_detail(request: Request, email_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    email = (
        db.query(EmailLog)
        .options(
            joinedload(EmailLog.detected_hotel),
            joinedload(EmailLog.assigned_bus_stop).joinedload(BusStop.city),
        )
        .filter(EmailLog.id == email_id)
        .first()
    )
    email.is_new = False
    db.commit()
    hotels = db.query(Hotel).order_by(Hotel.name).all()
    stops = db.query(BusStop).order_by(BusStop.name).all()
    return templates.TemplateResponse(
        "email_detail.html",
        template_context(request, user=user, email=email, hotels=hotels, stops=stops),
    )


@router.post("/{email_id}/send")
def send_email_reply(email_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    email = db.query(EmailLog).filter(EmailLog.id == email_id).first()
    if email.status == EmailStatus.cancelled:
        return RedirectResponse(url=f"/inbox/{email_id}", status_code=303)
    try:
        send_reply(email)
        email.status = EmailStatus.sent
        email.sent_at = datetime.now(UTC).replace(tzinfo=None)
    except Exception as exc:
        if email.status != EmailStatus.send_failed:
            email.status = EmailStatus.send_failed
        email.send_error = str(exc)
    email.is_new = False
    db.commit()
    return RedirectResponse(url=f"/inbox/{email_id}", status_code=303)


@router.post("/{email_id}/manual")
def flag_manual(email_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    email = db.query(EmailLog).filter(EmailLog.id == email_id).first()
    if email.status == EmailStatus.cancelled:
        return RedirectResponse(url=f"/inbox/{email_id}", status_code=303)
    email.status = EmailStatus.manual
    email.is_new = False
    db.commit()
    return RedirectResponse(url=f"/inbox/{email_id}", status_code=303)


@router.post("/{email_id}/reassign")
def reassign_email(
    email_id: int,
    detected_hotel_id: int = Form(...),
    assigned_bus_stop_id: int = Form(...),
    draft_reply: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    email = db.query(EmailLog).filter(EmailLog.id == email_id).first()
    if email.status == EmailStatus.cancelled:
        return RedirectResponse(url=f"/inbox/{email_id}", status_code=303)
    email.detected_hotel = db.query(Hotel).filter(Hotel.id == detected_hotel_id).first()
    email.assigned_bus_stop = db.query(BusStop).filter(BusStop.id == assigned_bus_stop_id).first()
    schedule_resolution = resolve_pickup_schedule(db, email.assigned_bus_stop, email.booking_type, email.cruise_date)
    email.pickup_time_text = (
        schedule_resolution.schedule.pickup_time.strftime("%H:%M")
        if schedule_resolution.schedule
        else MISSING_PICKUP_TIME_PLACEHOLDER
    )
    email.warning_note = schedule_resolution.warning_note
    regenerate_email_draft(email)
    if draft_reply.strip():
        email.draft_reply = draft_reply
    email.status = EmailStatus.pending
    db.commit()
    return RedirectResponse(url=f"/inbox/{email_id}", status_code=303)
