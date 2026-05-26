from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS_DIR = Path.home() / "Downloads"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rapidfuzz import fuzz
from sqlalchemy import func

from cruise_email_dashboard.database.db import SessionLocal, init_db, session_scope
from cruise_email_dashboard.database.models import BusStop, City, Hotel

CSV_CONFIG = (
    ("Sunny Beach", "sunny_beach_bus_pickup_properties.csv"),
    ("Obzor", "obzor_bus_pickup_properties.csv"),
    ("Pomorie", "pomorie_bus_pickup_properties.csv"),
)
SUNNY_BEACH_AREA_TO_STOP = {
    "north": "Helena / Zora - Main Road Bus Stop",
    "central": "Palm Court Bus Stop",
    "south": "Festa Panorama Ness Bus Stop",
}
FALLBACK_STOP_BY_CITY = {
    "Obzor": "Sunrise All Suite Resort",
    "Pomorie": "Saint George",
}


@dataclass
class ImportStats:
    added: int = 0
    updated: int = 0


def _candidate_csv_path(filename: str) -> Path:
    project_path = PROJECT_ROOT / filename
    if project_path.exists():
        return project_path
    downloads_path = DOWNLOADS_DIR / filename
    if downloads_path.exists():
        return downloads_path
    raise FileNotFoundError(f"Could not find CSV file {filename!r} in project root or Downloads.")


def _normalize_aliases(raw_aliases: str) -> str:
    aliases = []
    seen: set[str] = set()
    for alias in (raw_aliases or "").split(","):
        cleaned = alias.strip()
        lowered = cleaned.lower()
        if cleaned and lowered not in seen:
            seen.add(lowered)
            aliases.append(cleaned)
    return ",".join(aliases)


def _normalize_plus_code(code: str) -> str:
    return (code or "").strip().upper().replace(" ", "")


def _merged_aliases(existing_aliases: str, csv_aliases: str) -> str:
    merged = []
    seen: set[str] = set()
    for source in (existing_aliases or "", csv_aliases or ""):
        for alias in source.split(","):
            cleaned = alias.strip()
            lowered = cleaned.lower()
            if cleaned and lowered not in seen:
                seen.add(lowered)
                merged.append(cleaned)
    return ",".join(merged)


def _best_stop_for_name(stops: list[BusStop], hotel_name: str) -> BusStop | None:
    normalized_name = (hotel_name or "").strip().lower()
    best_stop: BusStop | None = None
    best_score = 0.0
    for stop in stops:
        candidates = [stop.name, stop.address or "", stop.description or ""]
        score = max(
            fuzz.partial_ratio(normalized_name, candidate.lower()) if candidate else 0.0
            for candidate in candidates
        )
        if score > best_score:
            best_stop = stop
            best_score = score
    return best_stop


def _bus_stop_for_row(city_name: str, area: str, hotel_name: str, db_session) -> BusStop:
    city = db_session.query(City).filter(City.name == city_name).first()
    if not city:
        raise ValueError(f"City {city_name!r} does not exist.")
    city_stops = db_session.query(BusStop).filter(BusStop.city_id == city.id).all()

    if city_name == "Sunny Beach":
        stop_name = SUNNY_BEACH_AREA_TO_STOP.get((area or "").strip().lower(), "Palm Court Bus Stop")
        stop = next((item for item in city_stops if item.name == stop_name), None)
        if stop:
            return stop
        raise ValueError(f"Sunny Beach stop {stop_name!r} not found.")

    matched_stop = _best_stop_for_name(city_stops, hotel_name)
    if matched_stop:
        return matched_stop

    fallback_name = FALLBACK_STOP_BY_CITY[city_name]
    fallback_stop = next((item for item in city_stops if item.name == fallback_name), None)
    if not fallback_stop:
        raise ValueError(f"Fallback stop {fallback_name!r} not found for {city_name}.")
    return fallback_stop


def import_hotels() -> tuple[ImportStats, dict[str, int]]:
    init_db()
    stats = ImportStats()
    with session_scope() as db:
        cities = {city.name: city for city in db.query(City).all()}
        for city_name, filename in CSV_CONFIG:
            city = cities.get(city_name)
            if not city:
                raise ValueError(f"City {city_name!r} not found in database.")
            csv_path = _candidate_csv_path(filename)
            with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    hotel_name = (row.get("name") or "").strip()
                    if not hotel_name:
                        continue
                    aliases = _normalize_aliases(row.get("aliases") or "")
                    plus_code = _normalize_plus_code(row.get("plus_code") or "")
                    existing = (
                        db.query(Hotel)
                        .filter(func.lower(Hotel.name) == hotel_name.lower())
                        .first()
                    )
                    if existing:
                        existing.aliases = _merged_aliases(existing.aliases, aliases)
                        existing.plus_code = plus_code or existing.plus_code
                        stats.updated += 1
                        continue

                    stop = _bus_stop_for_row(city_name, row.get("area") or "", hotel_name, db)
                    db.add(
                        Hotel(
                            name=hotel_name,
                            aliases=aliases,
                            plus_code=plus_code or None,
                            bus_stop_id=stop.id,
                            city_id=city.id,
                        )
                    )
                    stats.added += 1

        db.flush()
        totals = {
            city_name: db.query(Hotel).filter(Hotel.city_id == city.id).count()
            for city_name, city in cities.items()
        }
    return stats, totals


if __name__ == "__main__":
    stats, totals = import_hotels()
    print(f"Total hotels added: {stats.added}")
    print(f"Total hotels updated: {stats.updated}")
    for city_name in ("Sunny Beach", "Obzor", "Pomorie"):
        print(f"Total hotels in {city_name}: {totals.get(city_name, 0)}")
