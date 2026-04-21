from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr
import imaplib
import logging

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from cruise_email_dashboard.database.models import EmailLog, EmailStatus
from cruise_email_dashboard.services.classifier import classify_email
from cruise_email_dashboard.services.notifications import broker
from cruise_email_dashboard.services.reply_generator import regenerate_email_draft
from cruise_email_dashboard.services.scheduler import resolve_pickup_schedule
from cruise_email_dashboard.settings import settings

logger = logging.getLogger(__name__)


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
        detected_language=classification.language,
        status=EmailStatus.pending,
        booking_type=classification.booking_type,
        cruise_date=classification.cruise_date,
        cruise_time=classification.cruise_time,
        num_adults=classification.num_adults,
        customer_phone=classification.customer_phone,
        booking_number=classification.booking_number,
        gyg_ref=classification.gyg_ref,
        total_price=classification.total_price,
        raw_hotel_extraction=classification.raw_hotel_extraction,
        extraction_source=classification.extraction_source,
        warning_note=classification.warning_note,
    )

    if not classification.is_bus_request:
        email_log.status = EmailStatus.flagged
        email_log.warning_note = "Email did not match bus stop request keywords."
        db.add(email_log)
        db.flush()
        return email_log

    if not classification.matched_hotel:
        email_log.status = EmailStatus.flagged
        email_log.warning_note = classification.warning_note or "No hotel match found above the configured fuzzy threshold."
        db.add(email_log)
        db.flush()
        return email_log

    email_log.detected_hotel = classification.matched_hotel
    email_log.assigned_bus_stop = classification.matched_hotel.bus_stop

    if not email_log.assigned_bus_stop:
        email_log.status = EmailStatus.flagged
        email_log.warning_note = "Matched hotel has no assigned bus stop."
        db.add(email_log)
        db.flush()
        return email_log

    schedule_resolution = resolve_pickup_schedule(
        db,
        email_log.assigned_bus_stop,
        booking_type=email_log.booking_type,
        cruise_date=email_log.cruise_date,
    )
    email_log.pickup_time_text = schedule_resolution.schedule.pickup_time.strftime("%H:%M") if schedule_resolution.schedule else "To be confirmed"
    if schedule_resolution.warning_note:
        email_log.status = EmailStatus.flagged
        email_log.warning_note = "\n".join(part for part in [email_log.warning_note, schedule_resolution.warning_note] if part).strip()

    regenerate_email_draft(email_log)
    db.add(email_log)
    db.flush()
    return email_log


def poll_inbox_once(db: Session) -> int:
    if not settings.imap_host or not settings.imap_password:
        logger.info("IMAP credentials are not configured; skipping poll cycle.")
        return 0

    mailbox = imaplib.IMAP4_SSL(settings.imap_server, settings.imap_port)
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

    mailbox.close()
    mailbox.logout()
    return new_count


async def poll_forever(session_factory) -> None:
    while True:
        try:
            def _poll() -> int:
                with session_factory() as db:
                    count = poll_inbox_once(db)
                    db.commit()
                    return count

            new_count = await asyncio.to_thread(_poll)
            if new_count:
                await broker.publish("new_emails", {"count": new_count})
        except Exception as exc:
            logger.exception("Email poller cycle failed: %s", exc)
        await asyncio.sleep(max(settings.poll_interval_minutes, 1) * 60)
