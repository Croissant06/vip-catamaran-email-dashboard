from __future__ import annotations

import argparse
from email import message_from_bytes
import imaplib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cruise_email_dashboard.database.db import SessionLocal, init_db
from cruise_email_dashboard.database.models import EmailLog
from cruise_email_dashboard.services.email_poller import parse_received_at_header
from cruise_email_dashboard.settings import settings


def open_mailbox() -> imaplib.IMAP4_SSL:
    mail = imaplib.IMAP4_SSL(
        settings.imap_server,
        settings.imap_port,
        timeout=settings.mail_timeout_seconds,
    )
    mail.login(settings.imap_user, settings.imap_password)
    mail.select("INBOX", readonly=True)
    return mail


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill received_at from IMAP Date headers.")
    parser.add_argument(
        "--start-index",
        type=int,
        default=1,
        help="1-based position in the target list to resume from.",
    )
    args = parser.parse_args()

    init_db()
    with SessionLocal() as db:
        targets = (
            db.query(EmailLog)
            .filter(EmailLog.html_body.is_not(None), EmailLog.message_id.is_not(None))
            .order_by(EmailLog.id.asc())
            .all()
        )

    total = len(targets)
    if not total:
        print("[RECEIVED_AT] No rows require backfill.")
        return 0

    start_index = max(args.start_index, 1)
    targets = targets[start_index - 1 :]

    updated = 0
    skipped = 0

    mail = open_mailbox()
    try:
        for index, email in enumerate(targets, start=start_index):
            print(f"[RECEIVED_AT] {index}/{total} - {email.message_id}")
            try:
                status, data = mail.search(None, "HEADER", "Message-ID", email.message_id)
                ids = data[0].split() if status == "OK" and data and data[0] else []
                if not ids:
                    skipped += 1
                    continue

                status, message_data = mail.fetch(ids[-1], "(BODY.PEEK[HEADER.FIELDS (DATE)])")
                if status != "OK" or not message_data or not message_data[0]:
                    skipped += 1
                    continue

                header_bytes = message_data[0][1] or b""
                header_message = message_from_bytes(header_bytes)
                received_at = parse_received_at_header(header_message.get("Date"))

                with SessionLocal() as db:
                    row = db.query(EmailLog).filter(EmailLog.id == email.id).first()
                    if row:
                        row.received_at = received_at
                        db.commit()
                        updated += 1
            except Exception as exc:
                skipped += 1
                print(f"[RECEIVED_AT] ERROR at {index}/{total} - {email.message_id}: {exc}")
                try:
                    mail.close()
                except Exception:
                    pass
                try:
                    mail.logout()
                except Exception:
                    pass
                mail = open_mailbox()

        print(f"[RECEIVED_AT] Updated: {updated}")
        print(f"[RECEIVED_AT] Skipped: {skipped}")
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
