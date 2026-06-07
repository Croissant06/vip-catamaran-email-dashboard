from __future__ import annotations

from email.message import EmailMessage
import logging
import socket
import smtplib
import time

from cruise_email_dashboard.database.models import EmailLog, EmailStatus
from cruise_email_dashboard.settings import settings

logger = logging.getLogger(__name__)
MAX_SEND_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5
TRANSIENT_SMTP_CODES = {421, 450, 451, 452, 454}


def _recipient_for_email(email_log: EmailLog) -> str:
    if settings.demo_mode:
        return settings.demo_email
    return email_log.sender_email


def _decode_smtp_response(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


def _format_send_error(exc: Exception) -> str:
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        recipient, details = next(iter(exc.recipients.items()), (None, None))
        if recipient and isinstance(details, tuple) and len(details) >= 2:
            code, response = details[0], _decode_smtp_response(details[1])
            return f"SMTP {code} for {recipient}: {response}"
        return str(exc)
    if isinstance(exc, smtplib.SMTPResponseException):
        code = getattr(exc, "smtp_code", None)
        response = _decode_smtp_response(getattr(exc, "smtp_error", None))
        if code is not None and response:
            return f"SMTP {code}: {response}"
        if code is not None:
            return f"SMTP {code}: {exc}"
    return str(exc)


def _is_transient_smtp_error(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout, smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError)):
        return True
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        codes = [
            details[0]
            for details in exc.recipients.values()
            if isinstance(details, tuple) and details
        ]
        return any(code in TRANSIENT_SMTP_CODES or 400 <= code < 500 for code in codes)
    if isinstance(exc, smtplib.SMTPResponseException):
        code = getattr(exc, "smtp_code", None)
        return code in TRANSIENT_SMTP_CODES or (code is not None and 400 <= code < 500)
    message = str(exc).lower()
    transient_markers = (
        "timeout",
        "timed out",
        "temporary",
        "try again later",
        "connection reset",
        "connection unexpectedly closed",
        "temporarily unavailable",
    )
    return any(marker in message for marker in transient_markers)


def _raise_send_failure(email_log: EmailLog, exc: Exception, attempts: int) -> None:
    base_error = _format_send_error(exc)
    if attempts > 1:
        base_error = f"{base_error} (failed after {attempts} attempts)"
    email_log.status = EmailStatus.send_failed
    email_log.send_error = base_error
    raise RuntimeError(base_error) from exc


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

    for attempt in range(1, MAX_SEND_ATTEMPTS + 1):
        server = None
        try:
            server = smtplib.SMTP_SSL(settings.smtp_server, settings.smtp_port, timeout=settings.mail_timeout_seconds)
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
            email_log.send_error = ""
            return
        except smtplib.SMTPAuthenticationError as exc:
            logger.error(
                "[SMTP] Authentication failed for %s@%s:%s: %s",
                settings.smtp_user,
                settings.smtp_server,
                settings.smtp_port,
                _format_send_error(exc),
            )
            _raise_send_failure(email_log, exc, attempt)
        except Exception as exc:
            error_message = _format_send_error(exc)
            is_transient = _is_transient_smtp_error(exc)
            logger.error(
                "[SMTP] Send failed for email log %s on attempt %s/%s: %s",
                email_log.id,
                attempt,
                MAX_SEND_ATTEMPTS,
                error_message,
            )
            if is_transient and attempt < MAX_SEND_ATTEMPTS:
                logger.warning(
                    "[SMTP] Retrying transient send failure for email log %s in %s seconds.",
                    email_log.id,
                    RETRY_DELAY_SECONDS,
                )
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            _raise_send_failure(email_log, exc, attempt)
        finally:
            if server is not None:
                try:
                    server.quit()
                except Exception:
                    pass
