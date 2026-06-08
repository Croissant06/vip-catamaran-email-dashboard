from __future__ import annotations

from datetime import UTC, datetime
import threading
from typing import Callable

from cruise_email_dashboard.database.db import SessionLocal
from cruise_email_dashboard.database.models import EmailLog, EmailStatus
from cruise_email_dashboard.services.classifier import classify_email
from cruise_email_dashboard.services.email_poller import apply_classification_to_email
from cruise_email_dashboard.settings import settings

HotelReprocessStatus = dict[str, str | int | None]
HotelReprocessProgressCallback = Callable[[HotelReprocessStatus], None]

_status_lock = threading.Lock()
_hotel_reprocess_status: HotelReprocessStatus = {
    "status": "idle",
    "started_at": None,
    "finished_at": None,
    "total_selected": 0,
    "processed": 0,
    "updated": 0,
    "failed": 0,
    "message": "No reprocessing job has been started yet.",
}


def _copy_status() -> HotelReprocessStatus:
    with _status_lock:
        return dict(_hotel_reprocess_status)


def get_hotel_reprocess_status() -> HotelReprocessStatus:
    return _copy_status()


def _replace_hotel_reprocess_status(status: HotelReprocessStatus) -> HotelReprocessStatus:
    with _status_lock:
        _hotel_reprocess_status.clear()
        _hotel_reprocess_status.update(status)
        return dict(_hotel_reprocess_status)


def _set_hotel_reprocess_status(**updates) -> HotelReprocessStatus:
    with _status_lock:
        _hotel_reprocess_status.update(updates)
        return dict(_hotel_reprocess_status)


def _build_status(
    *,
    status: str,
    started_at: str | None = None,
    finished_at: str | None = None,
    total_selected: int = 0,
    processed: int = 0,
    updated: int = 0,
    failed: int = 0,
    message: str = "",
) -> HotelReprocessStatus:
    return {
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "total_selected": total_selected,
        "processed": processed,
        "updated": updated,
        "failed": failed,
        "message": message,
    }


def hotel_reprocess_is_running() -> bool:
    return get_hotel_reprocess_status().get("status") in {"queued", "running"}


def queue_hotel_reprocess() -> HotelReprocessStatus:
    if hotel_reprocess_is_running():
        return get_hotel_reprocess_status()
    return _replace_hotel_reprocess_status(
        _build_status(
            status="queued",
            started_at=datetime.now(UTC).isoformat(),
            message="Reprocessing started...",
        )
    )


def reprocess_flagged_emails(
    progress_callback: HotelReprocessProgressCallback | None = None,
) -> dict[str, int]:
    with SessionLocal() as db:
        target_ids = [
            row_id
            for (row_id,) in (
                db.query(EmailLog.id)
                .filter(EmailLog.status.in_([EmailStatus.flagged, EmailStatus.pending]))
                .order_by(EmailLog.id.asc())
                .all()
            )
        ]

    total_selected = len(target_ids)
    processed = 0
    updated = 0
    failed = 0

    def emit_progress() -> None:
        if progress_callback is None:
            return
        progress_callback(
            {
                "processed": processed,
                "total_selected": total_selected,
                "updated": updated,
                "failed": failed,
                "message": (
                    f"Reprocessing running... {processed} processed, "
                    f"{updated} updated, {failed} failed"
                ),
            }
        )

    emit_progress()

    for email_id in target_ids:
        with SessionLocal() as db:
            email = db.query(EmailLog).filter(EmailLog.id == email_id).first()
            if email is None:
                failed += 1
                processed += 1
                emit_progress()
                continue

            old_status = email.status
            try:
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
                db.commit()
                if old_status != new_status:
                    updated += 1
            except Exception:
                db.rollback()
                failed += 1

        processed += 1
        emit_progress()

    return {
        "processed": processed,
        "total_selected": total_selected,
        "updated": updated,
        "failed": failed,
    }


def run_hotel_reprocess_job() -> None:
    started_at = datetime.now(UTC).isoformat()
    _replace_hotel_reprocess_status(
        _build_status(
            status="running",
            started_at=started_at,
            message="Reprocessing running... 0 processed, 0 updated, 0 failed",
        )
    )

    try:
        summary = reprocess_flagged_emails(
            progress_callback=lambda update: _set_hotel_reprocess_status(**update),
        )
        _replace_hotel_reprocess_status(
            _build_status(
                status="completed",
                started_at=started_at,
                finished_at=datetime.now(UTC).isoformat(),
                total_selected=summary["total_selected"],
                processed=summary["processed"],
                updated=summary["updated"],
                failed=summary["failed"],
                message=(
                    f"Reprocessing complete - {summary['processed']} processed, "
                    f"{summary['updated']} updated, {summary['failed']} failed"
                ),
            )
        )
    except Exception as exc:
        snapshot = get_hotel_reprocess_status()
        _replace_hotel_reprocess_status(
            _build_status(
                status="failed",
                started_at=started_at,
                finished_at=datetime.now(UTC).isoformat(),
                total_selected=int(snapshot.get("total_selected") or 0),
                processed=int(snapshot.get("processed") or 0),
                updated=int(snapshot.get("updated") or 0),
                failed=int(snapshot.get("failed") or 0),
                message=f"Reprocessing failed - {exc}",
            )
        )
