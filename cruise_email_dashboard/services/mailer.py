from __future__ import annotations

from email.message import EmailMessage
import smtplib

from cruise_email_dashboard.database.models import EmailLog
from cruise_email_dashboard.settings import settings


def send_reply(email_log: EmailLog) -> None:
    if not settings.smtp_host or not settings.smtp_password:
        raise RuntimeError("SMTP credentials are not configured.")

    msg = EmailMessage()
    msg["Subject"] = (
        f"Re: Your VIP Catamaran Pickup Information - Booking {email_log.booking_number}"
        if email_log.booking_number
        else f"Re: {email_log.subject}"
    )
    msg["From"] = settings.smtp_user
    msg["To"] = email_log.sender_email
    msg.set_content(email_log.draft_reply)

    with smtplib.SMTP_SSL(settings.smtp_server, settings.smtp_port) as server:
        server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)
