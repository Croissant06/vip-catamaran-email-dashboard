from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
import re
import sys

from rapidfuzz import fuzz

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS_DIR = Path.home() / "Downloads"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cruise_email_dashboard.database.db import init_db, session_scope
from cruise_email_dashboard.database.models import City, Hotel

CSV_CONFIG = (
    ("Sunny Beach", DOWNLOADS_DIR / "sunny_beach_bus_pickup_properties.csv"),
    ("Obzor", DOWNLOADS_DIR / "obzor_bus_pickup_properties.csv"),
    ("Pomorie", DOWNLOADS_DIR / "pomorie_bus_pickup_properties.csv"),
)
MATCH_THRESHOLD = 80


@dataclass
class CsvRow:
    city_name: str
    name: str
    aliases: list[str]
    plus_code: str


def _normalize(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()
    return re.sub(r"\s+", " ", cleaned)


def _normalize_plus_code(value: str) -> str:
    return (value or "").strip().upper().replace(" ", "")


def _load_rows() -> list[CsvRow]:
    rows: list[CsvRow] = []
    for city_name, path in CSV_CONFIG:
        if not path.exists():
            raise FileNotFoundError(f"CSV not found: {path}")
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                plus_code = _normalize_plus_code(row.get("plus_code") or "")
                name = (row.get("name") or "").strip()
                if not name or not plus_code:
                    continue
                aliases = [alias.strip() for alias in (row.get("aliases") or "").split(",") if alias.strip()]
                rows.append(CsvRow(city_name=city_name, name=name, aliases=aliases, plus_code=plus_code))
    return rows


def _best_match(hotel: Hotel, rows: list[CsvRow]) -> CsvRow | None:
    hotel_name = _normalize(hotel.name)
    best_row: CsvRow | None = None
    best_score = 0.0
    for row in rows:
        candidates = [row.name, *row.aliases]
        score = max(fuzz.token_set_ratio(hotel_name, _normalize(candidate)) for candidate in candidates if candidate)
        if score > best_score:
            best_score = score
            best_row = row
    if best_row and best_score >= MATCH_THRESHOLD:
        return best_row
    return None


def merge_plus_codes() -> int:
    init_db()
    rows = _load_rows()
    updated = 0
    with session_scope() as db:
        city_by_id = {city.id: city.name for city in db.query(City).all()}
        hotels = db.query(Hotel).filter(Hotel.plus_code.is_(None)).all()
        for hotel in hotels:
            city_name = city_by_id.get(hotel.city_id)
            city_rows = [row for row in rows if row.city_name == city_name] if city_name else rows
            match = _best_match(hotel, city_rows)
            if not match:
                match = _best_match(hotel, rows)
            if not match:
                continue
            hotel.plus_code = match.plus_code
            updated += 1
    return updated


if __name__ == "__main__":
    updated = merge_plus_codes()
    print(f"Plus codes added: {updated}")
