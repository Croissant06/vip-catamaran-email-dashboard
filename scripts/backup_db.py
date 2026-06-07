from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "cruise_email_dashboard" / "app.db"
BACKUPS_DIR = ROOT / "backups"


def main() -> int:
    if not DB_PATH.exists():
        print(f"[BACKUP] Database not found: {DB_PATH}")
        return 1

    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    backup_path = BACKUPS_DIR / f"app_{timestamp}.db"
    shutil.copy2(DB_PATH, backup_path)
    print(f"[BACKUP] Created {backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
