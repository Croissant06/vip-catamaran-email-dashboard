from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cruise_email_dashboard.database.db import init_db, session_scope
from cruise_email_dashboard.database.models import BusStop


TARGET_STOP_NAME = "Marina Palas - with Minibus"
TARGET_MAPS_URL = "https://maps.app.goo.gl/S7mvX6Bg2SWRr8wJ6"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update the Marina Palas bus stop maps_url.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the before/after values without saving the change.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    init_db()

    with session_scope() as db:
        stop = db.query(BusStop).filter(BusStop.name == TARGET_STOP_NAME).one_or_none()
        if stop is None:
            print(f"[ERROR] Bus stop not found: {TARGET_STOP_NAME}")
            return 1

        before = stop.maps_url
        print(f"[BEFORE] {TARGET_STOP_NAME}: {before}")

        if args.dry_run:
            print("[DRY-RUN] No changes applied.")
            print(f"[AFTER]  {TARGET_STOP_NAME}: {TARGET_MAPS_URL}")
            return 0

        stop.maps_url = TARGET_MAPS_URL
        db.flush()

        print(f"[AFTER]  {TARGET_STOP_NAME}: {stop.maps_url}")
        if before == stop.maps_url:
            print("[INFO] maps_url already matched the target value.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
