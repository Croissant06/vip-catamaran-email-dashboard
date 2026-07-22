from __future__ import annotations

import argparse
from datetime import time
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cruise_email_dashboard.database.db import init_db, session_scope
from cruise_email_dashboard.database.models import BusStop, City, Hotel, Schedule, VehicleType


TARGET_CITY_NAME = "Obzor"
TARGET_STOP_NAME = "Clubhotel Miramar"
TARGET_STOP_ADDRESS = "Clubhotel Miramar"
TARGET_LATITUDE = 42.8170
TARGET_LONGITUDE = 27.8950
TARGET_MAPS_URL = "https://www.google.com/maps?q=42.8170,27.8950"
TARGET_DESCRIPTION = "outside Clubhotel Miramar"
TARGET_VEHICLE_TYPE = VehicleType.guide
TARGET_PICKUP_TIME = time(10, 15)
TARGET_SEASON_LABEL = "default"
TARGET_HOTELS = (
    ("Obzor Beach Resort", "Obzor Beach Resort"),
    ("Clubhotel Miramar", "Miramar"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ensure the Obzor Clubhotel Miramar stop, schedule, and hotels exist.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without saving changes.",
    )
    return parser.parse_args()


def _print_seed_note() -> None:
    print(
        "[NOTE] These coordinates are marked as unverified estimates in seed.py. "
        "Please confirm the Clubhotel Miramar pin with Olga on-site later."
    )


def main() -> int:
    args = parse_args()
    init_db()
    _print_seed_note()

    with session_scope() as db:
        city = db.query(City).filter(City.name == TARGET_CITY_NAME).one_or_none()
        if city is None:
            print(f"[ERROR] City not found: {TARGET_CITY_NAME}")
            return 1

        stop = (
            db.query(BusStop)
            .filter(BusStop.name == TARGET_STOP_NAME, BusStop.city_id == city.id)
            .one_or_none()
        )

        if stop is None:
            print(f"[CHECK] BusStop '{TARGET_STOP_NAME}' in {TARGET_CITY_NAME}: MISSING")
            stop_by_name = db.query(BusStop).filter(BusStop.name == TARGET_STOP_NAME).one_or_none()
            if stop_by_name is not None:
                print(
                    f"[WARN] Found BusStop named '{TARGET_STOP_NAME}' in a different city_id="
                    f"{stop_by_name.city_id}. This script only creates/ensures the Obzor row."
                )
            print(
                "[PLAN] Create BusStop with "
                f"address='{TARGET_STOP_ADDRESS}', lat={TARGET_LATITUDE}, lng={TARGET_LONGITUDE}, "
                f"maps_url='{TARGET_MAPS_URL}', description='{TARGET_DESCRIPTION}', "
                f"vehicle_type='{TARGET_VEHICLE_TYPE.value}'."
            )
            if not args.dry_run:
                stop = BusStop(
                    name=TARGET_STOP_NAME,
                    address=TARGET_STOP_ADDRESS,
                    latitude=TARGET_LATITUDE,
                    longitude=TARGET_LONGITUDE,
                    maps_url=TARGET_MAPS_URL,
                    description=TARGET_DESCRIPTION,
                    vehicle_type=TARGET_VEHICLE_TYPE,
                    city_id=city.id,
                )
                db.add(stop)
                db.flush()
                print(f"[CREATED] BusStop '{TARGET_STOP_NAME}' (id={stop.id})")
        else:
            print(
                f"[CHECK] BusStop '{TARGET_STOP_NAME}' in {TARGET_CITY_NAME}: FOUND "
                f"(id={stop.id}, maps_url='{stop.maps_url}')"
            )

        schedule = None
        if stop is not None:
            schedule = (
                db.query(Schedule)
                .filter(
                    Schedule.bus_stop_id == stop.id,
                    Schedule.pickup_time == TARGET_PICKUP_TIME,
                    Schedule.season_label == TARGET_SEASON_LABEL,
                )
                .one_or_none()
            )

        if stop is None:
            print(
                f"[PLAN] Create Schedule for '{TARGET_STOP_NAME}' at "
                f"{TARGET_PICKUP_TIME.strftime('%H:%M')} with season_label='{TARGET_SEASON_LABEL}'."
            )
        elif schedule is None:
            print(
                f"[CHECK] Schedule for '{TARGET_STOP_NAME}' at "
                f"{TARGET_PICKUP_TIME.strftime('%H:%M')} / '{TARGET_SEASON_LABEL}': MISSING"
            )
            if not args.dry_run:
                schedule = Schedule(
                    bus_stop_id=stop.id,
                    pickup_time=TARGET_PICKUP_TIME,
                    season_label=TARGET_SEASON_LABEL,
                )
                db.add(schedule)
                db.flush()
                print(f"[CREATED] Schedule id={schedule.id} for BusStop '{TARGET_STOP_NAME}'")
        else:
            print(
                f"[CHECK] Schedule for '{TARGET_STOP_NAME}' at "
                f"{TARGET_PICKUP_TIME.strftime('%H:%M')} / '{TARGET_SEASON_LABEL}': FOUND "
                f"(id={schedule.id})"
            )

        for hotel_name, aliases in TARGET_HOTELS:
            hotel = (
                db.query(Hotel)
                .filter(Hotel.name == hotel_name, Hotel.city_id == city.id)
                .one_or_none()
            )

            if hotel is None:
                hotel_by_name = db.query(Hotel).filter(Hotel.name == hotel_name).one_or_none()
                if hotel_by_name is not None:
                    print(
                        f"[WARN] Found Hotel '{hotel_name}' outside {TARGET_CITY_NAME} "
                        f"(city_id={hotel_by_name.city_id})."
                    )
                print(f"[CHECK] Hotel '{hotel_name}' in {TARGET_CITY_NAME}: MISSING")
                print(
                    f"[PLAN] Create Hotel '{hotel_name}' with aliases='{aliases}', "
                    f"bus_stop='{TARGET_STOP_NAME}', city='{TARGET_CITY_NAME}'."
                )
                if not args.dry_run and stop is not None:
                    hotel = Hotel(
                        name=hotel_name,
                        aliases=aliases,
                        bus_stop_id=stop.id,
                        city_id=city.id,
                    )
                    db.add(hotel)
                    db.flush()
                    print(f"[CREATED] Hotel '{hotel_name}' (id={hotel.id})")
            else:
                print(
                    f"[CHECK] Hotel '{hotel_name}' in {TARGET_CITY_NAME}: FOUND "
                    f"(id={hotel.id}, aliases='{hotel.aliases}', bus_stop_id={hotel.bus_stop_id})"
                )

        if args.dry_run:
            print("[DRY-RUN] No changes applied.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
