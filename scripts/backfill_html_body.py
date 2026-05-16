from __future__ import annotations

from email import message_from_bytes
import imaplib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cruise_email_dashboard.database.db import SessionLocal, init_db
from cruise_email_dashboard.database.models import EmailLog
from cruise_email_dashboard.services.email_poller import _extract_bodies
from cruise_email_dashboard.settings import settings


def main() -> int:
    init_db()
    with SessionLocal() as db:
        targets = db.query(EmailLog).filter(EmailLog.html_body.is_(None)).order_by(EmailLog.id.asc()).all()

    total = len(targets)
    if not total:
        print("[BACKFILL] No emails require html_body backfill.")
        return 0

    mail = imaplib.IMAP4_SSL(settings.imap_server, settings.imap_port, timeout=settings.mail_timeout_seconds)
    try:
        mail.login(settings.imap_user, settings.imap_password)
        mail.select("INBOX")

        for index, email in enumerate(targets, start=1):
            print(f"[BACKFILL] {index}/{total} - {email.message_id or 'NO_MESSAGE_ID'}")
            if not email.message_id:
                print("[BACKFILL] Skipped: no message_id stored.")
                continue

            status, data = mail.search(None, "HEADER", "Message-ID", email.message_id)
            ids = data[0].split() if status == "OK" and data and data[0] else []
            if not ids:
                print("[BACKFILL] Skipped: message not found on IMAP server.")
                continue

            status, message_data = mail.fetch(ids[-1], "(RFC822)")
            if status != "OK" or not message_data or not message_data[0]:
                print("[BACKFILL] Skipped: failed to fetch message.")
                continue

            raw_email = message_data[0][1]
            message = message_from_bytes(raw_email)
            _, html_body = _extract_bodies(message)
            if not html_body:
                print("[BACKFILL] Skipped: no html body found in message.")
                continue

            with SessionLocal() as db:
                row = db.query(EmailLog).filter(EmailLog.id == email.id).first()
                if row:
                    row.html_body = html_body
                    db.commit()
        return 0
    finally:
        try:
            mail.close()
        except Exception:
            pass
        try:
            mail.logout()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
