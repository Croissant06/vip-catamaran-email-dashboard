from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cruise_email_dashboard.services.history_import import import_historical_emails


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import all historical inbox emails without changing read state.")
    parser.add_argument("--limit", type=int, default=0, help="Import only the first N emails from the oldest side of the inbox.")
    parser.add_argument("--since", type=str, default="", help="Only import emails on or after YYYY-MM-DD using IMAP SINCE search.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        summary = import_historical_emails(
            since_date=args.since,
            limit=args.limit,
            log_callback=print,
        )
    except Exception as exc:
        print(f"[IMPORT] {exc}")
        return 1

    print(f"Total found on server: {summary['total_found']}")
    print(f"Already in DB (skipped): {summary['skipped_existing']}")
    print(f"Newly imported: {summary['imported']}")
    print(f"Failed to parse: {summary['failed']}")
    print(f"Reprocess improved: {summary['improved']}")
    print(f"Reprocess still flagged: {summary['still_flagged']}")
    print(f"Reprocess skipped sent: {summary['skipped_sent']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
