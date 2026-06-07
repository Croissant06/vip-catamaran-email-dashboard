from __future__ import annotations

import imaplib
import smtplib

from cruise_email_dashboard.services.poll_state import load_poll_state
from cruise_email_dashboard.settings import settings


def _open_smtp_connection() -> smtplib.SMTP:
    if settings.smtp_use_starttls:
        server = smtplib.SMTP(settings.smtp_server, settings.smtp_port, timeout=settings.mail_timeout_seconds)
        server.ehlo()
        server.starttls()
        server.ehlo()
        return server
    return smtplib.SMTP_SSL(settings.smtp_server, settings.smtp_port, timeout=settings.mail_timeout_seconds)


def mailbox_status() -> dict[str, str | int | bool | None]:
    imap_status = "error"
    smtp_status = "error"
    imap_message = "IMAP not tested"
    smtp_message = "SMTP not tested"

    try:
        mailbox = imaplib.IMAP4_SSL(settings.imap_server, settings.imap_port, timeout=settings.mail_timeout_seconds)
        try:
            mailbox.login(settings.imap_user, settings.imap_password)
        finally:
            try:
                mailbox.logout()
            except Exception:
                pass
        imap_status = "ok"
        imap_message = f"Connected to {settings.imap_server}:{settings.imap_port}"
    except Exception as exc:
        imap_message = str(exc)

    try:
        server = _open_smtp_connection()
        try:
            server.login(settings.smtp_user, settings.smtp_password)
            code, response = server.noop()
        finally:
            try:
                server.quit()
            except Exception:
                pass
        smtp_status = "ok" if code == 250 else "error"
        smtp_message = f"Connected to {settings.smtp_server}:{settings.smtp_port} ({code} {response.decode() if isinstance(response, bytes) else response})"
    except Exception as exc:
        smtp_message = str(exc)

    return {
        "imap": imap_status,
        "smtp": smtp_status,
        "imap_message": imap_message,
        "smtp_message": smtp_message,
        **load_poll_state(),
    }
