from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from email import message_from_bytes
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import imaplib

from cruise_email_dashboard.database.db import SessionLocal, init_db
from cruise_email_dashboard.database.models import EmailLog, EmailStatus
from cruise_email_dashboard.services.classifier import classify_email
from cruise_email_dashboard.services.email_poller import _decode_header, _extract_bodies, apply_classification_to_email, parse_received_at_header, process_message
from cruise_email_dashboard.settings import settings

EMAIL_TIMEOUT_SECONDS = 15


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import all historical inbox emails without changing read state.")
    parser.add_argument("--limit", type=int, default=0, help="Import only the first N emails from the oldest side of the inbox.")
    parser.add_argument("--since", type=str, default="", help="Only import emails on or after YYYY-MM-DD using IMAP SINCE search.")
    return parser.parse_args()


def reprocess_existing_rows() -> dict[str, int]:
    improved = 0
    still_flagged = 0
    skipped_sent = 0

    with SessionLocal() as db:
        skipped_sent = db.query(EmailLog).filter(EmailLog.status == EmailStatus.sent).count()
        targets = (
            db.query(EmailLog)
            .filter(EmailLog.status.in_([EmailStatus.flagged, EmailStatus.pending]))
            .order_by(EmailLog.id.asc())
            .all()
        )

        for email in targets:
            old_status = email.status
            classified = classify_email(
                db,
                subject=email.subject or "",
                body=email.full_body or "",
                threshold=settings.fuzzy_match_threshold,
                html_body=email.html_body or "",
                fallback_sender=email.sender_email or "",
                fallback_name=email.sender_name or "",
            )
            _, new_status = apply_classification_to_email(db, email, classified, improvement_only=False)
            if old_status != new_status:
                improved += 1
            if new_status == EmailStatus.flagged:
                still_flagged += 1
        db.commit()

    return {
        "improved": improved,
        "still_flagged": still_flagged,
        "skipped_sent": skipped_sent,
    }


def fetch_message_id(mail: imaplib.IMAP4_SSL, email_id: bytes) -> str | None:
    status, data = mail.fetch(email_id, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
    if status != "OK" or not data or not data[0]:
        return None
    header_bytes = data[0][1] or b""
    header_text = header_bytes.decode("utf-8", errors="ignore")
    for line in header_text.splitlines():
        if line.lower().startswith("message-id:"):
            return line.split(":", 1)[1].strip() or None
    return None


def import_single_email(email_id: bytes) -> tuple[str, str | None]:
    mail = imaplib.IMAP4_SSL(settings.imap_server, settings.imap_port, timeout=settings.mail_timeout_seconds)
    try:
        mail.login(settings.imap_user, settings.imap_password)
        mail.select("INBOX", readonly=True)
        status, message_data = mail.fetch(email_id, "(BODY.PEEK[])")
        if status != "OK" or not message_data or not message_data[0]:
            return "failed", None

        raw_email = message_data[0][1]
        message = message_from_bytes(raw_email)
        message_id_header = message.get("Message-ID")
        text_body, html_body = _extract_bodies(message)
        received_at = parse_received_at_header(message.get("Date"))

        with SessionLocal() as db:
            if message_id_header and db.query(EmailLog).filter(EmailLog.message_id == message_id_header).first():
                return "skipped", message_id_header
            email_log = process_message(
                db=db,
                message_id=message_id_header,
                sender=_decode_header(message.get("From")),
                subject=_decode_header(message.get("Subject")),
                text_body=text_body,
                html_body=html_body,
                received_at=received_at,
            )
            if email_log is None:
                return "skipped", message_id_header
            db.commit()
        return "imported", message_id_header
    finally:
        try:
            mail.close()
        except Exception:
            pass
        try:
            mail.logout()
        except Exception:
            pass


def main() -> int:
    args = parse_args()
    init_db()

    if not settings.imap_host or not settings.imap_password:
        print("[IMPORT] IMAP credentials are not configured.")
        return 1

    total_found = 0
    skipped_existing = 0
    imported = 0
    failed = 0

    mail = imaplib.IMAP4_SSL(settings.imap_server, settings.imap_port, timeout=settings.mail_timeout_seconds)
    try:
        mail.login(settings.imap_user, settings.imap_password)
        mail.select("INBOX", readonly=True)

        if args.since:
            since_date = datetime.strptime(args.since, "%Y-%m-%d")
            since_imap = since_date.strftime("%d-%b-%Y")
            status, data = mail.search(None, "SINCE", since_imap)
        else:
            status, data = mail.search(None, "ALL")
        if status != "OK":
            print("[IMPORT] Failed to search mailbox.")
            return 1

        all_ids = data[0].split() if data and data[0] else []
        total_found = len(all_ids)
        ids = all_ids[: args.limit] if args.limit and args.limit > 0 else all_ids
        batch_total = len(ids)

        with ThreadPoolExecutor(max_workers=1) as executor:
            for index, email_id in enumerate(ids, start=1):
                message_id_header = None
                try:
                    message_id_header = fetch_message_id(mail, email_id)
                except Exception:
                    failed += 1
                    print(f"[IMPORT] FAILED header fetch on email {email_id.decode(errors='ignore')}")
                    if index % 10 == 0 or index == batch_total:
                        print(f"[IMPORT] {index}/{batch_total}")
                    continue

                printable_message_id = message_id_header or "NO_MESSAGE_ID"

                with SessionLocal() as db:
                    if message_id_header and db.query(EmailLog).filter(EmailLog.message_id == message_id_header).first():
                        skipped_existing += 1
                        print(f"[IMPORT] {index}/{batch_total} - {printable_message_id}")
                        if index % 10 == 0 or index == batch_total:
                            print(f"[IMPORT] {index}/{batch_total}")
                        continue

                future = executor.submit(import_single_email, email_id)
                try:
                    result, returned_message_id = future.result(timeout=EMAIL_TIMEOUT_SECONDS)
                    printable_message_id = returned_message_id or printable_message_id
                    if result == "imported":
                        imported += 1
                    elif result == "skipped":
                        skipped_existing += 1
                    else:
                        failed += 1
                        print(f"[IMPORT] FAILED - {printable_message_id}")
                    print(f"[IMPORT] {index}/{batch_total} - {printable_message_id}")
                except FutureTimeoutError:
                    failed += 1
                    print(f"[IMPORT] TIMEOUT on email {email_id.decode(errors='ignore')} - skipping")
                except Exception:
                    failed += 1
                    print(f"[IMPORT] FAILED - {printable_message_id}")

                if index % 10 == 0 or index == batch_total:
                    print(f"[IMPORT] {index}/{batch_total}")

        reprocess_summary = reprocess_existing_rows()

        print(f"Total found on server: {total_found}")
        print(f"Already in DB (skipped): {skipped_existing}")
        print(f"Newly imported: {imported}")
        print(f"Failed to parse: {failed}")
        print(f"Reprocess improved: {reprocess_summary['improved']}")
        print(f"Reprocess still flagged: {reprocess_summary['still_flagged']}")
        print(f"Reprocess skipped sent: {reprocess_summary['skipped_sent']}")
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
