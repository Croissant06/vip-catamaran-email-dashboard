from __future__ import annotations

from datetime import datetime, timedelta
import os
from pathlib import Path
import sqlite3
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "cruise_email_dashboard" / "app.db"
DEFAULT_BACKUPS_DIR = ROOT / "backups"
DEFAULT_LOG_PATH = DEFAULT_BACKUPS_DIR / "backup.log"
DEFAULT_RETENTION_DAYS = 14


def resolve_db_path() -> Path:
    explicit_path = os.getenv("BACKUP_DB_PATH", "").strip()
    if explicit_path:
        return Path(explicit_path).expanduser().resolve()

    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url.startswith("sqlite:///"):
        raw_path = database_url.removeprefix("sqlite:///")
        db_path = Path(raw_path)
        if not db_path.is_absolute():
            db_path = (ROOT / db_path).resolve()
        return db_path

    return DEFAULT_DB_PATH.resolve()


def resolve_backups_dir() -> Path:
    explicit_dir = os.getenv("BACKUP_DIR", "").strip()
    if explicit_dir:
        return Path(explicit_dir).expanduser().resolve()
    return DEFAULT_BACKUPS_DIR.resolve()


def resolve_log_path(backups_dir: Path) -> Path:
    explicit_path = os.getenv("BACKUP_LOG_PATH", "").strip()
    if explicit_path:
        return Path(explicit_path).expanduser().resolve()
    return (backups_dir / DEFAULT_LOG_PATH.name).resolve()


def retention_days() -> int:
    raw_value = os.getenv("BACKUP_RETENTION_DAYS", str(DEFAULT_RETENTION_DAYS)).strip()
    return max(int(raw_value), 0)


def timestamp_now() -> datetime:
    return datetime.now()


def _sqlite_string(path: Path) -> str:
    return str(path).replace("'", "''")


def log_event(log_path: Path, level: str, message: str, now: datetime | None = None) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = (now or timestamp_now()).strftime("%Y-%m-%d %H:%M:%S")
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp} [{level}] {message}\n")


def prune_old_backups(backups_dir: Path, retention_days: int, now: datetime | None = None) -> list[Path]:
    reference_time = now or timestamp_now()
    cutoff = reference_time - timedelta(days=retention_days)
    deleted: list[Path] = []

    for candidate in backups_dir.glob("app_*.db"):
        modified_at = datetime.fromtimestamp(candidate.stat().st_mtime)
        if modified_at < cutoff:
            candidate.unlink(missing_ok=True)
            deleted.append(candidate)

    return deleted


def create_sqlite_backup(
    *,
    db_path: Path,
    backups_dir: Path,
    log_path: Path,
    now: datetime | None = None,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> Path:
    reference_time = now or timestamp_now()
    backups_dir.mkdir(parents=True, exist_ok=True)

    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    backup_path = backups_dir / f"app_{reference_time.strftime('%Y-%m-%d_%H-%M')}.db"
    if backup_path.exists():
        backup_path.unlink()

    with sqlite3.connect(db_path) as connection:
        connection.execute(f"VACUUM INTO '{_sqlite_string(backup_path)}'")

    deleted = prune_old_backups(backups_dir, retention_days, now=reference_time)
    log_message = (
        f"Created backup {backup_path} from {db_path}. "
        f"Deleted {len(deleted)} backups older than {retention_days} days."
    )
    log_event(log_path, "SUCCESS", log_message, now=reference_time)
    return backup_path


def main() -> int:
    db_path = resolve_db_path()
    backups_dir = resolve_backups_dir()
    log_path = resolve_log_path(backups_dir)
    keep_days = retention_days()

    try:
        backup_path = create_sqlite_backup(
            db_path=db_path,
            backups_dir=backups_dir,
            log_path=log_path,
            retention_days=keep_days,
        )
    except Exception as exc:
        log_event(log_path, "FAILURE", f"Backup failed for {db_path}: {exc}")
        print(f"[BACKUP] Failed: {exc}")
        return 1

    print(f"[BACKUP] Created {backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
