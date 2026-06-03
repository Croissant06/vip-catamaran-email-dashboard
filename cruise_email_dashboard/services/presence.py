from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from cruise_email_dashboard.database.models import User, UserPresence, UserRole

ACTIVE_WINDOW_SECONDS = 60
SCHEDULED_CLEANUP_SECONDS = 120

USERNAME_COLORS = {
    "tickets": "bg-indigo-500",
    "bookings": "bg-green-500",
    "info": "bg-orange-500",
    "admin": "bg-red-500",
}


def utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def active_cutoff() -> datetime:
    return utc_now_naive() - timedelta(seconds=ACTIVE_WINDOW_SECONDS)


def scheduled_cleanup_cutoff() -> datetime:
    return utc_now_naive() - timedelta(seconds=SCHEDULED_CLEANUP_SECONDS)


def cleanup_stale_presence(db: Session, *, older_than: datetime) -> list[int]:
    stale_email_ids = [
        email_id
        for (email_id,) in db.query(UserPresence.email_log_id).filter(UserPresence.last_seen < older_than).distinct().all()
    ]
    if not stale_email_ids:
        return []
    db.query(UserPresence).filter(UserPresence.last_seen < older_than).delete(synchronize_session=False)
    db.commit()
    return stale_email_ids


def _presence_color(user: User) -> str:
    return USERNAME_COLORS.get(user.username, "bg-gray-500" if user.role == UserRole.staff else "bg-red-500")


def _presence_payload(user: User) -> dict[str, str]:
    username = user.username
    return {
        "username": username,
        "initial": username[:1].upper(),
        "color": _presence_color(user),
    }


def _active_presence_rows(db: Session, email_ids: list[int], requesting_user_id: int) -> list[UserPresence]:
    if not email_ids:
        return []
    return (
        db.query(UserPresence)
        .options(joinedload(UserPresence.user))
        .filter(UserPresence.email_log_id.in_(email_ids))
        .filter(UserPresence.last_seen >= active_cutoff())
        .filter(UserPresence.user_id != requesting_user_id)
        .order_by(UserPresence.email_log_id.asc(), UserPresence.last_seen.desc())
        .all()
    )


def get_active_presence_for_email(db: Session, email_log_id: int, requesting_user_id: int) -> list[dict[str, str]]:
    rows = _active_presence_rows(db, [email_log_id], requesting_user_id)
    seen_user_ids: set[int] = set()
    result: list[dict[str, str]] = []
    for row in rows:
        if row.user_id in seen_user_ids:
            continue
        seen_user_ids.add(row.user_id)
        result.append(_presence_payload(row.user))
    return result


def get_active_presence_batch(db: Session, email_ids: list[int], requesting_user_id: int) -> dict[str, list[dict[str, str]]]:
    rows = _active_presence_rows(db, email_ids, requesting_user_id)
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen_pairs: set[tuple[int, int]] = set()
    for row in rows:
        pair = (row.email_log_id, row.user_id)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        grouped[str(row.email_log_id)].append(_presence_payload(row.user))
    return {str(email_id): grouped.get(str(email_id), []) for email_id in email_ids}
