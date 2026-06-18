from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload

from cruise_email_dashboard.database.db import get_db
from cruise_email_dashboard.database.models import BusStop, EmailLog, EmailStatus, Hotel, User
from cruise_email_dashboard.dependencies import get_current_user, template_context, templates
from cruise_email_dashboard.services.csrf import validate_csrf
from cruise_email_dashboard.services.mailer import send_reply
from cruise_email_dashboard.services.reply_generator import MISSING_PICKUP_TIME_PLACEHOLDER, regenerate_email_draft
from cruise_email_dashboard.services.scheduler import resolve_pickup_schedule

router = APIRouter(prefix="/inbox", tags=["inbox"], dependencies=[Depends(validate_csrf)])
SOFIA_TZ = ZoneInfo("Europe/Sofia")
DEFAULT_QUICK_RANGE = "last_7_days"


def _today_local() -> date:
    return datetime.now(SOFIA_TZ).date()


def _quick_range_dates(quick_range: str) -> tuple[str, str]:
    today = _today_local()
    if quick_range == "today":
        start = end = today
    elif quick_range == "last_30_days":
        start = today - timedelta(days=29)
        end = today
    else:
        start = today - timedelta(days=6)
        end = today
    return start.isoformat(), end.isoformat()


def _filter_summary(quick_range: str, start_date: str, end_date: str) -> str:
    labels = {
        "today": "today",
        "last_7_days": "the last 7 days",
        "last_30_days": "the last 30 days",
        "all": "all dates",
    }
    if quick_range in labels:
        return labels[quick_range]
    if start_date and end_date:
        return f"{start_date} to {end_date}"
    if start_date:
        return f"{start_date} onward"
    if end_date:
        return f"through {end_date}"
    return "all dates"


def _wants_json_response(request: Request) -> bool:
    accept = request.headers.get("accept", "").lower()
    requested_with = request.headers.get("x-requested-with", "").lower()
    return "application/json" in accept or requested_with == "xmlhttprequest"


def _normalized_return_to(return_to: str) -> str:
    return "logs" if return_to == "logs" else ""


def _detail_query_suffix(return_to: str) -> str:
    normalized = _normalized_return_to(return_to)
    return f"?return_to={quote_plus(normalized)}" if normalized else ""


def _detail_redirect_url(email_id: int, return_to: str) -> str:
    return f"/inbox/{email_id}{_detail_query_suffix(return_to)}"


@router.get("")
def inbox_page(
    request: Request,
    status: str = Query(default=""),
    language: str = Query(default=""),
    start_date: str = Query(default=""),
    end_date: str = Query(default=""),
    quick_range: str = Query(default=""),
    highlight: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    has_explicit_filters = any(
        value
        for value in [status, language, start_date, end_date, quick_range]
    )
    saved_filters = request.session.get("inbox_filters", {})

    if not has_explicit_filters and saved_filters:
        status = saved_filters.get("status", "")
        language = saved_filters.get("language", "")
        start_date = saved_filters.get("start_date", "")
        end_date = saved_filters.get("end_date", "")
        quick_range = saved_filters.get("quick_range", DEFAULT_QUICK_RANGE)
    elif not has_explicit_filters:
        quick_range = DEFAULT_QUICK_RANGE

    if quick_range in {"today", "last_7_days", "last_30_days"}:
        start_date, end_date = _quick_range_dates(quick_range)
    elif quick_range == "all":
        start_date = ""
        end_date = ""
    elif start_date or end_date:
        quick_range = "custom"
    else:
        quick_range = DEFAULT_QUICK_RANGE
        start_date, end_date = _quick_range_dates(quick_range)

    request.session["inbox_filters"] = {
        "status": status,
        "language": language,
        "start_date": start_date,
        "end_date": end_date,
        "quick_range": quick_range,
    }

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
            filters={
                "status": status,
                "language": language,
                "start_date": start_date,
                "end_date": end_date,
                "quick_range": quick_range,
            },
            filtered_count=len(emails),
            filter_summary=_filter_summary(quick_range, start_date, end_date),
            highlight_id=highlight,
        ),
    )


@router.get("/{email_id}")
def email_detail(
    request: Request,
    email_id: int,
    return_to: str = Query(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
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
    normalized_return_to = _normalized_return_to(return_to)
    return templates.TemplateResponse(
        "email_detail.html",
        template_context(
            request,
            user=user,
            email=email,
            hotels=hotels,
            stops=stops,
            return_to=normalized_return_to,
            detail_query_suffix=_detail_query_suffix(normalized_return_to),
            back_href="/logs" if normalized_return_to == "logs" else "/inbox",
            back_label="Back to History & Logs" if normalized_return_to == "logs" else "Back to Inbox",
        ),
    )


@router.post("/{email_id}/send")
def send_email_reply(
    email_id: int,
    request: Request,
    return_to: str = Query(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    normalized_return_to = _normalized_return_to(return_to)
    email = db.query(EmailLog).filter(EmailLog.id == email_id).first()
    if email.status == EmailStatus.cancelled:
        if _wants_json_response(request):
            return JSONResponse({"ok": False, "status": email.status.value, "send_error": ""}, status_code=400)
        return RedirectResponse(url=_detail_redirect_url(email_id, normalized_return_to), status_code=303)
    send_succeeded = False
    try:
        send_reply(email)
        email.status = EmailStatus.sent
        email.sent_at = datetime.now(UTC).replace(tzinfo=None)
        email.send_error = ""
        send_succeeded = True
    except Exception as exc:
        if email.status != EmailStatus.send_failed:
            email.status = EmailStatus.send_failed
        email.send_error = str(exc)
    email.is_new = False
    db.commit()
    if _wants_json_response(request):
        return JSONResponse(
            {
                "ok": send_succeeded,
                "status": email.status.value,
                "send_error": email.send_error or "",
                "sent_at": email.sent_at.strftime("%Y-%m-%d %H:%M") if email.sent_at else "",
            }
        )
    return RedirectResponse(url=_detail_redirect_url(email_id, normalized_return_to), status_code=303)


@router.post("/{email_id}/manual")
def flag_manual(
    email_id: int,
    return_to: str = Query(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    normalized_return_to = _normalized_return_to(return_to)
    email = db.query(EmailLog).filter(EmailLog.id == email_id).first()
    if email.status == EmailStatus.cancelled:
        return RedirectResponse(url=_detail_redirect_url(email_id, normalized_return_to), status_code=303)
    email.status = EmailStatus.manual
    email.is_new = False
    db.commit()
    return RedirectResponse(url=_detail_redirect_url(email_id, normalized_return_to), status_code=303)


@router.post("/{email_id}/mark-unread")
def mark_email_unread(
    email_id: int,
    request: Request,
    return_to: str = Query(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    normalized_return_to = _normalized_return_to(return_to)
    email = db.query(EmailLog).filter(EmailLog.id == email_id).first()
    if email:
        email.is_new = True
        db.commit()
    if _wants_json_response(request):
        return JSONResponse({"ok": bool(email), "is_new": bool(email and email.is_new)})
    return RedirectResponse(url=_detail_redirect_url(email_id, normalized_return_to), status_code=303)


@router.post("/{email_id}/reassign")
def reassign_email(
    email_id: int,
    detected_hotel_id: int = Form(...),
    assigned_bus_stop_id: int = Form(...),
    draft_reply: str = Form(...),
    return_to: str = Query(default=""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    normalized_return_to = _normalized_return_to(return_to)
    email = db.query(EmailLog).filter(EmailLog.id == email_id).first()
    if email.status == EmailStatus.cancelled:
        return RedirectResponse(url=_detail_redirect_url(email_id, normalized_return_to), status_code=303)
    existing_draft_reply = email.draft_reply or ""
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
    if draft_reply.strip() and draft_reply.strip() != existing_draft_reply.strip():
        email.draft_reply = draft_reply
    email.status = EmailStatus.pending
    db.commit()
    return RedirectResponse(url=_detail_redirect_url(email_id, normalized_return_to), status_code=303)
