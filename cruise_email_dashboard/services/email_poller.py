from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr
import imaplib
import logging
import socket
import smtplib

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from cruise_email_dashboard.database.models import EmailLog, EmailStatus
from cruise_email_dashboard.services.classifier import classify_email
from cruise_email_dashboard.services.notifications import broker
from cruise_email_dashboard.services.poll_state import ensure_poll_state_file, load_poll_state, reset_backoff_state, update_poll_state
from cruise_email_dashboard.services.reply_generator import MISSING_PICKUP_TIME_PLACEHOLDER, regenerate_email_draft
from cruise_email_dashboard.services.scheduler import resolve_pickup_schedule
from cruise_email_dashboard.settings import settings

logger = logging.getLogger(__name__)
_poll_lock = asyncio.Lock()


def _choose_status(old_status: EmailStatus, new_status: EmailStatus, improvement_only: bool) -> EmailStatus:
    if not improvement_only:
        return new_status
    if old_status == EmailStatus.sent:
        return old_status
    if new_status == EmailStatus.cancelled and old_status != EmailStatus.cancelled:
        return EmailStatus.cancelled
    if old_status == EmailStatus.flagged and new_status == EmailStatus.pending:
        return EmailStatus.pending
    return old_status


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _decode_payload(part: Message) -> str:
    payload = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="ignore")


def _extract_bodies(message: Message) -> tuple[str, str]:
    text_body = ""
    html_body = ""
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in content_disposition:
                continue
            if content_type == "text/plain" and not text_body:
                text_body = _decode_payload(part)
            if content_type == "text/html" and not html_body:
                html_body = _decode_payload(part)
    else:
        if message.get_content_type() == "text/html":
            html_body = _decode_payload(message)
        else:
            text_body = _decode_payload(message)
    return text_body, html_body


def _is_auth_failure(exc: Exception) -> bool:
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return True
    message = str(exc).lower()
    return isinstance(exc, imaplib.IMAP4.error) and ("login" in message or "authentication" in message)


def _backoff_window_active() -> bool:
    state = load_poll_state()
    if not state["backoff_active"] or not state["last_attempt"]:
        return False
    last_attempt = datetime.fromisoformat(state["last_attempt"])
    return datetime.now(UTC) < last_attempt + timedelta(minutes=max(settings.poll_backoff_minutes, 1))


def _mark_success() -> None:
    state = load_poll_state()
    restored = state["backoff_active"]
    update_poll_state(
        last_success=datetime.now(UTC).isoformat(),
        last_error="",
        backoff_active=False,
        consecutive_failures=0,
    )
    if restored:
        logger.info("[POLL] Connection restored")


def _mark_failure(exc: Exception, auth_failure: bool) -> None:
    state = load_poll_state()
    consecutive_failures = int(state["consecutive_failures"] or 0) + 1
    update_poll_state(
        last_error=str(exc),
        backoff_active=auth_failure or state["backoff_active"],
        consecutive_failures=consecutive_failures,
    )
    if auth_failure:
        logger.error(
            "[POLL] Authentication failure detected. Backing off for %s minute(s): %s",
            settings.poll_backoff_minutes,
            exc,
        )
    else:
        logger.error("[POLL] Poll cycle failed: %s", exc)


def apply_classification_to_email(
    db: Session,
    email_log: EmailLog,
    classification,
    *,
    improvement_only: bool = False,
) -> tuple[EmailStatus, EmailStatus]:
    old_status = email_log.status or EmailStatus.pending

    email_log.sender_email = classification.customer_email or email_log.sender_email
    email_log.sender_name = classification.customer_name or email_log.sender_name or "Guest"
    email_log.detected_language = classification.language
    email_log.template_language = classification.language
    email_log.booking_type = classification.booking_type or ""
    email_log.cruise_date = classification.cruise_date
    email_log.cruise_time = classification.cruise_time
    email_log.num_adults = classification.num_adults
    email_log.num_children = classification.num_children
    email_log.customer_phone = classification.customer_phone or ""
    email_log.booking_number = classification.booking_number or ""
    email_log.gyg_ref = classification.gyg_ref or ""
    email_log.total_price = classification.total_price or ""
    email_log.detected_city = classification.detected_city_name or ""
    email_log.raw_customer_name_extraction = classification.raw_customer_name_extraction or ""
    email_log.raw_hotel_extraction = classification.raw_hotel_extraction or ""
    email_log.extraction_source = classification.extraction_source or ""
    email_log.warning_note = classification.warning_note or ""

    if classification.resolved_status == EmailStatus.cancelled:
        email_log.detected_hotel = None
        email_log.assigned_bus_stop = None
        email_log.pickup_time_text = ""
        email_log.draft_reply = ""
        email_log.status = _choose_status(old_status, EmailStatus.cancelled, improvement_only)
        return old_status, email_log.status

    if not classification.is_bus_request:
        email_log.detected_hotel = None
        email_log.assigned_bus_stop = None
        email_log.pickup_time_text = ""
        email_log.draft_reply = ""
        email_log.status = _choose_status(old_status, EmailStatus.flagged, improvement_only)
        if not email_log.warning_note:
            email_log.warning_note = "Email did not match bus stop request keywords."
        return old_status, email_log.status

    email_log.detected_hotel = classification.matched_hotel
    email_log.assigned_bus_stop = classification.matched_bus_stop or (classification.matched_hotel.bus_stop if classification.matched_hotel else None)

    if not classification.matched_hotel and not classification.matched_bus_stop:
        email_log.pickup_time_text = ""
        email_log.draft_reply = ""
        email_log.status = _choose_status(old_status, EmailStatus.flagged, improvement_only)
        if not email_log.warning_note:
            email_log.warning_note = "No hotel match found above the configured fuzzy threshold."
        return old_status, email_log.status

    if not email_log.assigned_bus_stop:
        email_log.pickup_time_text = ""
        email_log.draft_reply = ""
        email_log.status = _choose_status(old_status, EmailStatus.flagged, improvement_only)
        email_log.warning_note = "\n".join(
            part for part in [email_log.warning_note, "Matched hotel has no assigned bus stop."] if part
        ).strip()
        return old_status, email_log.status

    schedule_resolution = resolve_pickup_schedule(
        db,
        email_log.assigned_bus_stop,
        booking_type=email_log.booking_type,
        cruise_date=email_log.cruise_date,
    )
    email_log.pickup_time_text = (
        schedule_resolution.schedule.pickup_time.strftime("%H:%M")
        if schedule_resolution.schedule
        else MISSING_PICKUP_TIME_PLACEHOLDER
    )
    if schedule_resolution.warning_note:
        email_log.warning_note = "\n".join(
            part for part in [email_log.warning_note, schedule_resolution.warning_note] if part
        ).strip()

    if classification.selected_stop_time_text and schedule_resolution.schedule:
        resolved_time = schedule_resolution.schedule.pickup_time.strftime("%H:%M")
        if classification.selected_stop_time_text != resolved_time:
            mismatch_note = (
                f"Customer selected stop includes time {classification.selected_stop_time_text}, "
                f"but schedule resolved to {resolved_time}."
            )
            email_log.warning_note = "\n".join(part for part in [email_log.warning_note, mismatch_note] if part).strip()

    if schedule_resolution.warning_note and "Pomorie operates Tuesday and Friday only" in schedule_resolution.warning_note:
        target_status = EmailStatus.flagged
    else:
        target_status = EmailStatus.pending
    email_log.status = _choose_status(old_status, target_status, improvement_only)
    regenerate_email_draft(email_log)
    return old_status, email_log.status


def process_message(
    db: Session,
    message_id: str | None,
    sender: str,
    subject: str,
    text_body: str,
    html_body: str = "",
) -> EmailLog:
    sender_name, sender_email = parseaddr(sender)
    plain_text_body = text_body or (BeautifulSoup(html_body, "html.parser").get_text("\n", strip=True) if html_body else "")
    classification = classify_email(
        db,
        subject=subject,
        body=plain_text_body,
        threshold=settings.fuzzy_match_threshold,
        html_body=html_body,
        fallback_sender=sender_email or sender,
        fallback_name=sender_name,
    )
    email_log = EmailLog(
        message_id=message_id,
        received_at=datetime.now(UTC).replace(tzinfo=None),
        sender_email=classification.customer_email or sender_email or sender,
        sender_name=classification.customer_name or sender_name or "Guest",
        subject=subject,
        body_snippet=plain_text_body.strip()[:280],
        full_body=plain_text_body or html_body or "",
        html_body=html_body or None,
        detected_language=classification.language,
        status=EmailStatus.pending,
        booking_type=classification.booking_type,
        cruise_date=classification.cruise_date,
        cruise_time=classification.cruise_time,
        num_adults=classification.num_adults,
        num_children=classification.num_children,
        customer_phone=classification.customer_phone,
        booking_number=classification.booking_number,
        gyg_ref=classification.gyg_ref,
        total_price=classification.total_price,
        detected_city=classification.detected_city_name or "",
        raw_customer_name_extraction=classification.raw_customer_name_extraction,
        raw_hotel_extraction=classification.raw_hotel_extraction,
        extraction_source=classification.extraction_source,
        warning_note=classification.warning_note,
    )
    apply_classification_to_email(db, email_log, classification, improvement_only=False)
    db.add(email_log)
    db.flush()
    return email_log


def poll_inbox_once(db: Session) -> int:
    if not settings.imap_host or not settings.imap_password:
        logger.info("[POLL] IMAP credentials are not configured; skipping poll cycle.")
        return 0

    mailbox = None
    try:
        mailbox = imaplib.IMAP4_SSL(settings.imap_server, settings.imap_port, timeout=settings.mail_timeout_seconds)
        mailbox.login(settings.imap_user, settings.imap_password)
        mailbox.select("INBOX")
        _, data = mailbox.search(None, "UNSEEN")
        ids = data[0].split()
        new_count = 0

        for email_id in ids:
            _, message_data = mailbox.fetch(email_id, "(RFC822)")
            raw_email = message_data[0][1]
            message = message_from_bytes(raw_email)
            message_id_header = message.get("Message-ID")

            if message_id_header and db.query(EmailLog).filter(EmailLog.message_id == message_id_header).first():
                mailbox.store(email_id, "+FLAGS", "\\Seen")
                continue

            text_body, html_body = _extract_bodies(message)
            process_message(
                db=db,
                message_id=message_id_header,
                sender=_decode_header(message.get("From")),
                subject=_decode_header(message.get("Subject")),
                text_body=text_body,
                html_body=html_body,
            )
            mailbox.store(email_id, "+FLAGS", "\\Seen")
            new_count += 1

        return new_count
    finally:
        if mailbox is not None:
            try:
                mailbox.close()
            except Exception:
                pass
            try:
                mailbox.logout()
            except Exception:
                pass


def run_poll_cycle(session_factory, force: bool = False) -> dict[str, str | int | bool]:
    ensure_poll_state_file()
    state = load_poll_state()
    if state["backoff_active"] and _backoff_window_active() and not force:
        return {"status": "skipped", "message": "Backoff active; poll skipped."}

    update_poll_state(last_attempt=datetime.now(UTC).isoformat())
    try:
        with session_factory() as db:
            new_count = poll_inbox_once(db)
            db.commit()
        _mark_success()
        if new_count:
            logger.info("[POLL] %s new email(s) found", new_count)
        return {"status": "ok", "new_count": new_count}
    except Exception as exc:
        auth_failure = _is_auth_failure(exc)
        _mark_failure(exc, auth_failure=auth_failure)
        return {"status": "error", "message": str(exc), "auth_failure": auth_failure}


async def poll_now(session_factory, force: bool = False) -> dict[str, str | int | bool]:
    async with _poll_lock:
        result = await asyncio.to_thread(run_poll_cycle, session_factory, force)
        if result.get("status") == "ok" and result.get("new_count"):
            await broker.publish("new_emails", {"count": result["new_count"]})
        return result


async def poll_forever(session_factory) -> None:
    ensure_poll_state_file()
    while True:
        try:
            await poll_now(session_factory)
        except (socket.timeout, TimeoutError, OSError) as exc:
            _mark_failure(exc, auth_failure=False)
        except Exception as exc:
            auth_failure = _is_auth_failure(exc)
            _mark_failure(exc, auth_failure=auth_failure)
        await asyncio.sleep(max(settings.poll_interval_minutes, 1) * 60)


def reset_poll_backoff() -> dict[str, str | int | bool | None]:
    return reset_backoff_state()
