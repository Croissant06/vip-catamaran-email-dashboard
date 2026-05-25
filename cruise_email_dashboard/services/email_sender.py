from __future__ import annotations

from email.message import EmailMessage
import logging
import smtplib

from cruise_email_dashboard.database.models import EmailLog, EmailStatus
from cruise_email_dashboard.settings import settings

logger = logging.getLogger(__name__)


def _recipient_for_email(email_log: EmailLog) -> str:
    if settings.demo_mode:
        return settings.demo_email
    return email_log.sender_email


def send_reply(email_log: EmailLog) -> None:
    if settings.safe_mode:
        raise RuntimeError("SAFE_MODE is enabled; outbound email is disabled.")
    if not settings.smtp_host or not settings.smtp_password:
        raise RuntimeError("SMTP credentials are not configured.")
    if settings.demo_mode and not settings.demo_email:
        raise RuntimeError("DEMO_MODE is enabled but DEMO_EMAIL is not configured.")

    msg = EmailMessage()
    msg["Subject"] = (
        f"Re: Your VIP Catamaran Pickup Information - Booking {email_log.booking_number}"
        if email_log.booking_number
        else f"Re: {email_log.subject}"
    )
    msg["From"] = settings.smtp_user
    msg["To"] = _recipient_for_email(email_log)
    msg.set_content(email_log.draft_reply)

    server = None
    try:
        server = smtplib.SMTP_SSL(settings.smtp_server, settings.smtp_port, timeout=settings.mail_timeout_seconds)
        server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)
        email_log.send_error = ""
    except smtplib.SMTPAuthenticationError as exc:
        logger.error("[SMTP] Authentication failed for %s@%s:%s: %s", settings.smtp_user, settings.smtp_server, settings.smtp_port, exc)
        email_log.status = EmailStatus.send_failed
        email_log.send_error = str(exc)
        raise
    except Exception as exc:
        logger.error("[SMTP] Send failed for email log %s: %s", email_log.id, exc)
        email_log.status = EmailStatus.send_failed
        email_log.send_error = str(exc)
        raise
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass
