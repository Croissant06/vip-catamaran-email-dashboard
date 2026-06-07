from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import UTC, datetime
from email import message_from_bytes
from email.utils import parseaddr
import imaplib
import threading
from typing import Callable

from bs4 import BeautifulSoup
from sqlalchemy import func

from cruise_email_dashboard.database.db import SessionLocal, init_db
from cruise_email_dashboard.database.models import EmailLog, EmailStatus
from cruise_email_dashboard.services.classifier import classify_email
from cruise_email_dashboard.services.email_poller import (
    _decode_header,
    _extract_bodies,
    apply_classification_to_email,
    parse_received_at_header,
    process_message,
)
from cruise_email_dashboard.settings import settings

EMAIL_TIMEOUT_SECONDS = 15
HistoryImportStatus = dict[str, str | int | bool | None]
HistoryImportProgressCallback = Callable[[HistoryImportStatus], None]
HistoryImportLogCallback = Callable[[str], None]

_status_lock = threading.Lock()
_history_import_status: HistoryImportStatus = {
    "status": "idle",
    "since_date": "",
    "limit": 0,
    "started_at": None,
    "finished_at": None,
    "total_found": 0,
    "total_selected": 0,
    "processed": 0,
    "imported": 0,
    "skipped_existing": 0,
    "failed": 0,
    "improved": 0,
    "still_flagged": 0,
    "skipped_sent": 0,
    "message": "No historical import has been started yet.",
}


def _copy_status() -> HistoryImportStatus:
    with _status_lock:
        return dict(_history_import_status)


def get_history_import_status() -> HistoryImportStatus:
    return _copy_status()


def _set_history_import_status(**updates) -> HistoryImportStatus:
    with _status_lock:
        _history_import_status.update(updates)
        return dict(_history_import_status)


def _replace_history_import_status(status: HistoryImportStatus) -> HistoryImportStatus:
    with _status_lock:
        _history_import_status.clear()
        _history_import_status.update(status)
        return dict(_history_import_status)


def _normalized_sender_email(sender_value: str) -> str:
    _, sender_email = parseaddr(sender_value or "")
    return sender_email.strip().lower()


def _message_body_fingerprint(text_body: str, html_body: str) -> str:
    plain_text_body = text_body or (BeautifulSoup(html_body, "html.parser").get_text("\n", strip=True) if html_body else "")
    return plain_text_body.strip()[:280]


def _find_existing_email(
    db,
    *,
    message_id: str | None,
    sender: str,
    subject: str,
    received_at: datetime,
    text_body: str,
    html_body: str,
) -> EmailLog | None:
    if message_id:
        existing = db.query(EmailLog).filter(EmailLog.message_id == message_id).first()
        if existing:
            return existing

    sender_email = _normalized_sender_email(sender)
    fingerprint = _message_body_fingerprint(text_body, html_body)
    if not sender_email or not subject:
        return None

    return (
        db.query(EmailLog)
        .filter(
            EmailLog.message_id.is_(None),
            func.lower(EmailLog.sender_email) == sender_email,
            EmailLog.subject == subject,
            EmailLog.received_at == received_at,
            EmailLog.body_snippet == fingerprint,
        )
        .first()
    )


def reprocess_existing_rows() -> dict[str, int]:
    improved = 0
    still_flagged = 0

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
        sender = _decode_header(message.get("From"))
        subject = _decode_header(message.get("Subject"))
        text_body, html_body = _extract_bodies(message)
        received_at = parse_received_at_header(message.get("Date"))

        with SessionLocal() as db:
            if _find_existing_email(
                db,
                message_id=message_id_header,
                sender=sender,
                subject=subject,
                received_at=received_at,
                text_body=text_body,
                html_body=html_body,
            ):
                return "skipped", message_id_header

            email_log = process_message(
                db=db,
                message_id=message_id_header,
                sender=sender,
                subject=subject,
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


def import_historical_emails(
    *,
    since_date: str = "",
    limit: int = 0,
    progress_callback: HistoryImportProgressCallback | None = None,
    log_callback: HistoryImportLogCallback | None = None,
) -> dict[str, int]:
    init_db()

    if not settings.imap_host or not settings.imap_password:
        raise RuntimeError("IMAP credentials are not configured.")

    total_found = 0
    skipped_existing = 0
    imported = 0
    failed = 0

    def emit_log(message: str) -> None:
        if log_callback:
            log_callback(message)

    def emit_progress(processed: int, total_selected: int) -> None:
        if not progress_callback:
            return
        progress_callback(
            {
                "processed": processed,
                "total_selected": total_selected,
                "imported": imported,
                "skipped_existing": skipped_existing,
                "failed": failed,
                "message": (
                    f"Import running... {processed} processed so far "
                    f"({imported} new, {skipped_existing} skipped, {failed} failed)"
                ),
            }
        )

    mail = imaplib.IMAP4_SSL(settings.imap_server, settings.imap_port, timeout=settings.mail_timeout_seconds)
    try:
        mail.login(settings.imap_user, settings.imap_password)
        mail.select("INBOX", readonly=True)

        if since_date:
            parsed_since_date = datetime.strptime(since_date, "%Y-%m-%d")
            since_imap = parsed_since_date.strftime("%d-%b-%Y")
            status, data = mail.search(None, "SINCE", since_imap)
        else:
            status, data = mail.search(None, "ALL")
        if status != "OK":
            raise RuntimeError("Failed to search mailbox.")

        all_ids = data[0].split() if data and data[0] else []
        total_found = len(all_ids)
        ids = all_ids[: limit] if limit and limit > 0 else all_ids
        batch_total = len(ids)

        if progress_callback:
            progress_callback(
                {
                    "total_found": total_found,
                    "total_selected": batch_total,
                    "processed": 0,
                    "imported": 0,
                    "skipped_existing": 0,
                    "failed": 0,
                    "message": f"Import running... 0 processed so far (0 new, 0 skipped, 0 failed)",
                }
            )

        with ThreadPoolExecutor(max_workers=1) as executor:
            for index, email_id in enumerate(ids, start=1):
                message_id_header = None
                try:
                    message_id_header = fetch_message_id(mail, email_id)
                except Exception:
                    failed += 1
                    emit_log(f"[IMPORT] FAILED header fetch on email {email_id.decode(errors='ignore')}")
                    emit_progress(index, batch_total)
                    continue

                printable_message_id = message_id_header or "NO_MESSAGE_ID"

                with SessionLocal() as db:
                    if message_id_header and db.query(EmailLog).filter(EmailLog.message_id == message_id_header).first():
                        skipped_existing += 1
                        emit_log(f"[IMPORT] {index}/{batch_total} - {printable_message_id}")
                        emit_progress(index, batch_total)
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
                        emit_log(f"[IMPORT] FAILED - {printable_message_id}")
                    emit_log(f"[IMPORT] {index}/{batch_total} - {printable_message_id}")
                except FutureTimeoutError:
                    failed += 1
                    emit_log(f"[IMPORT] TIMEOUT on email {email_id.decode(errors='ignore')} - skipping")
                except Exception:
                    failed += 1
                    emit_log(f"[IMPORT] FAILED - {printable_message_id}")

                emit_progress(index, batch_total)

        reprocess_summary = reprocess_existing_rows()
        return {
            "total_found": total_found,
            "total_selected": len(ids),
            "processed": len(ids),
            "skipped_existing": skipped_existing,
            "imported": imported,
            "failed": failed,
            "improved": reprocess_summary["improved"],
            "still_flagged": reprocess_summary["still_flagged"],
            "skipped_sent": reprocess_summary["skipped_sent"],
        }
    finally:
        try:
            mail.close()
        except Exception:
            pass
        try:
            mail.logout()
        except Exception:
            pass


def _build_status(
    *,
    status: str,
    since_date: str,
    limit: int,
    started_at: str | None = None,
    finished_at: str | None = None,
    total_found: int = 0,
    total_selected: int = 0,
    processed: int = 0,
    imported: int = 0,
    skipped_existing: int = 0,
    failed: int = 0,
    improved: int = 0,
    still_flagged: int = 0,
    skipped_sent: int = 0,
    message: str = "",
) -> HistoryImportStatus:
    return {
        "status": status,
        "since_date": since_date,
        "limit": limit,
        "started_at": started_at,
        "finished_at": finished_at,
        "total_found": total_found,
        "total_selected": total_selected,
        "processed": processed,
        "imported": imported,
        "skipped_existing": skipped_existing,
        "failed": failed,
        "improved": improved,
        "still_flagged": still_flagged,
        "skipped_sent": skipped_sent,
        "message": message,
    }


def historical_import_is_running() -> bool:
    return get_history_import_status().get("status") in {"queued", "running"}


def queue_historical_import(*, since_date: str, limit: int = 0) -> HistoryImportStatus:
    if historical_import_is_running():
        return get_history_import_status()
    now = datetime.now(UTC).isoformat()
    return _replace_history_import_status(
        _build_status(
            status="queued",
            since_date=since_date,
            limit=limit,
            started_at=now,
            message=f"Import queued for {since_date}.",
        )
    )


def run_historical_import_job(*, since_date: str, limit: int = 0) -> None:
    started_at = datetime.now(UTC).isoformat()
    _replace_history_import_status(
        _build_status(
            status="running",
            since_date=since_date,
            limit=limit,
            started_at=started_at,
            message="Import running... 0 processed so far (0 new, 0 skipped, 0 failed)",
        )
    )

    try:
        summary = import_historical_emails(
            since_date=since_date,
            limit=limit,
            progress_callback=lambda update: _set_history_import_status(**update),
        )
        finished_at = datetime.now(UTC).isoformat()
        _replace_history_import_status(
            _build_status(
                status="completed",
                since_date=since_date,
                limit=limit,
                started_at=started_at,
                finished_at=finished_at,
                total_found=summary["total_found"],
                total_selected=summary["total_selected"],
                processed=summary["processed"],
                imported=summary["imported"],
                skipped_existing=summary["skipped_existing"],
                failed=summary["failed"],
                improved=summary["improved"],
                still_flagged=summary["still_flagged"],
                skipped_sent=summary["skipped_sent"],
                message=f"Import complete - {summary['imported']} new emails added",
            )
        )
    except Exception as exc:
        failed_snapshot = get_history_import_status()
        _replace_history_import_status(
            _build_status(
                status="failed",
                since_date=since_date,
                limit=limit,
                started_at=started_at,
                finished_at=datetime.now(UTC).isoformat(),
                total_found=int(failed_snapshot.get("total_found") or 0),
                total_selected=int(failed_snapshot.get("total_selected") or 0),
                processed=int(failed_snapshot.get("processed") or 0),
                imported=int(failed_snapshot.get("imported") or 0),
                skipped_existing=int(failed_snapshot.get("skipped_existing") or 0),
                failed=int(failed_snapshot.get("failed") or 0),
                improved=int(failed_snapshot.get("improved") or 0),
                still_flagged=int(failed_snapshot.get("still_flagged") or 0),
                skipped_sent=int(failed_snapshot.get("skipped_sent") or 0),
                message=f"Import failed - {exc}",
            )
        )
