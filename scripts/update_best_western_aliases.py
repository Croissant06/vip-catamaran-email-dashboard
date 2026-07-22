from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cruise_email_dashboard.database.db import init_db, session_scope
from cruise_email_dashboard.database.models import Hotel


TARGET_HOTEL_NAME = "Best Western / Sveshest"
ALIASES_TO_ADD = ("Spiders Pub", "Spider's Pub")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Append Spider's Pub aliases to the Best Western / Sveshest hotel.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the before/after aliases without saving the change.",
    )
    return parser.parse_args()


def merge_aliases(existing_aliases: str, aliases_to_add: tuple[str, ...]) -> str:
    merged: list[str] = []
    seen: set[str] = set()

    for alias in (existing_aliases or "").split(","):
        cleaned = alias.strip()
        lowered = cleaned.lower()
        if cleaned and lowered not in seen:
            seen.add(lowered)
            merged.append(cleaned)

    for alias in aliases_to_add:
        cleaned = alias.strip()
        lowered = cleaned.lower()
        if cleaned and lowered not in seen:
            seen.add(lowered)
            merged.append(cleaned)

    return ",".join(merged)


def main() -> int:
    args = parse_args()
    init_db()

    with session_scope() as db:
        hotel = db.query(Hotel).filter(Hotel.name == TARGET_HOTEL_NAME).one_or_none()
        if hotel is None:
            print(f"[ERROR] Hotel not found: {TARGET_HOTEL_NAME}")
            return 1

        before = hotel.aliases or ""
        after = merge_aliases(before, ALIASES_TO_ADD)

        print(f"[BEFORE] {TARGET_HOTEL_NAME}: {before}")

        if args.dry_run:
            print("[DRY-RUN] No changes applied.")
            print(f"[AFTER]  {TARGET_HOTEL_NAME}: {after}")
            return 0

        hotel.aliases = after
        db.flush()

        print(f"[AFTER]  {TARGET_HOTEL_NAME}: {hotel.aliases}")
        if before == hotel.aliases:
            print("[INFO] Aliases already included the requested values.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
