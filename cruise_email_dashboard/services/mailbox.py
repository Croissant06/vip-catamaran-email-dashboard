from __future__ import annotations

import imaplib
import smtplib

from cruise_email_dashboard.settings import settings


def mailbox_status() -> dict[str, str]:
    imap_status = "error"
    smtp_status = "error"
    imap_message = "IMAP not tested"
    smtp_message = "SMTP not tested"

    try:
        mailbox = imaplib.IMAP4_SSL(settings.imap_server, settings.imap_port)
        mailbox.login(settings.imap_user, settings.imap_password)
        mailbox.logout()
        imap_status = "ok"
        imap_message = f"Connected to {settings.imap_server}:{settings.imap_port}"
    except Exception as exc:
        imap_message = str(exc)

    try:
        with smtplib.SMTP_SSL(settings.smtp_server, settings.smtp_port) as server:
            server.login(settings.smtp_user, settings.smtp_password)
            code, response = server.noop()
        smtp_status = "ok" if code == 250 else "error"
        smtp_message = f"Connected to {settings.smtp_server}:{settings.smtp_port} ({code} {response.decode() if isinstance(response, bytes) else response})"
    except Exception as exc:
        smtp_message = str(exc)

    return {
        "imap": imap_status,
        "smtp": smtp_status,
        "imap_message": imap_message,
        "smtp_message": smtp_message,
    }
