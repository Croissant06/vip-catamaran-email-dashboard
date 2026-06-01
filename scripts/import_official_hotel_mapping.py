from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sys

from rapidfuzz import fuzz

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cruise_email_dashboard.database.db import init_db, session_scope
from cruise_email_dashboard.database.models import BusStop, City, Hotel

SUNNY_BEACH_CITY = "Sunny Beach"

STOP_NAME_MAP = {
    "VLAS - PETROL STATION": "Vlas - Petrol Station",
    "MERCURY GRAND MARKET": "Mercury Grand Market",
    "SECRETS RESORT": "Secrets Resort - Main Road Bus Stop",
    "HELENA / ZORA": "Helena / Zora - Main Road Bus Stop",
    "EFIR BUS STOP": "Efir Bus Stop",
    "PALM COURT BUS STOP": "Palm Court Bus Stop",
    "OPAL BUS STOP": "Opal Bus Stop",
    "FLOWER STREET MAIN BUS STOP": "Flower Street Main Bus Stop",
    "BEST WESTERN / SVESHEST": "Hotel Best Western / Sveshest",
    "ROYAL SUN / ARDA BUS STOP": "Royal Sun / Arda Bus Stop",
    "BLACK SEA HOTEL BUS STOP": "Black Sea Hotel Bus Stop",
    "BELLEVILLE / CACAO BUS STOP": "Belleville / Cacao Bus Stop",
    "FOOTBALL STADIUM BUS STOP": "Football Stadium Bus Stop",
    "AQUA PARADISE HOTEL - WITH MINIBUS": "Aqua Paradise Hotel - with Minibus",
    "SOL NESSEBAR PALAS - WITH MINIBUS": "SOL Nessebar Palas - with Minibus",
    "FESTA PANORAMA NESS BUS STOP": "Festa Panorama Ness Bus Stop",
    "PANTELEIMON BUS STOP - WITH MINIBUS": "Panteleimon Bus Stop - with Minibus",
    "BILIYANA NESS - WITH MINIBUS": "Biliyana Ness - with Minibus",
    "OASIS NESS - WITH MINIBUS": "Oasis Ness - with Minibus",
    "MARINA PALAS - WITH MINIBUS": "Marina Palas - with Minibus",
}

OFFICIAL_MAPPING: dict[str, list[str]] = {
    "VLAS - PETROL STATION": [
        "Voya Beach Resort",
        "Family Hotel Rainbow",
        "Hotel Peshev",
        "Hotel Sveti Vlas",
        "Saint George Palace",
        "Sea Dreams",
        "Hotel Serenity",
    ],
    "MERCURY GRAND MARKET": [
        "Premier Fort Beach",
        "Premier Fort Club",
        "Panorama Dreams",
        "Sea Wind Apartments",
        "Sorento Sole Mare",
        "Grand Hotel Sveti Vlas",
    ],
    "SECRETS RESORT": [
        "Belle Air Apartments",
        "The Poolhouse Sunny Beach",
        "Holiday Apartments Vista del mar 2",
        "Relax Holiday Complex & Spa",
    ],
    "HELENA / ZORA": [
        "Hotel Helena Park",
        "Hotel Bora Bora",
        "Hotel Helena Sands",
        "Hotel Zenith",
        "Hotel Sunny Bay",
        "Complex Sunrise by HMG All Inclusive",
        "Hotel Sunrise Club",
        "Carina Beach",
    ],
    "EFIR BUS STOP": [
        "DIT Majestic Beach Resort",
        "Hotel Poseydon",
        "Hotel Marvel",
        "Family Hotel Gold Pearl",
        "Imperial Palace Hotel",
        "Sunny Beach Plaza",
        "MPM Hotel Condor",
        "Hotel Bellevue Sunny Beach",
        "Palace Hotel Sunny Beach",
        "DIT Evrika Beach Club Hotel",
        "Hotel Flamingo",
        "Hotel Slavyanski",
        "Hotel Sunny Day Club",
        "Hotel Ivana Palace",
        "Friends Family Hotel",
        "Sunny Sea Palace",
        "TSB Sunny Victory Aparthotel",
    ],
    "PALM COURT BUS STOP": [
        "Hotel Wella",
        "iHotel",
        "Hotel Platinum",
        "Hotel Heaven",
        "Magnolia Garden",
        "Harmony Suites Monte Carlo",
        "Hotel Lion",
        "Hotel Palma",
        "Harmony Suites 6",
        "Cascadas Family Resort",
        "Dawn Park",
        "Dawn Park Deluxe",
        "APARTELLO Balkan Breeze 7",
        "Hotel Riva",
        "Garden Nevis",
        "Hotel Glarus",
        "Yassen Holiday Village",
        "Regina Hotel",
    ],
    "OPAL BUS STOP": [
        "Sol e Mar",
        "Effect Grand Victoria Hotel",
        "Chaika Beach Resort",
        "PERLA TUI SUNEO All Inclusive",
        "Hotel Karlovo",
        "Sokol",
        "Grand Hotel Sunny Beach",
        "Hotel Oleander House",
        "Hotel Klisura",
        "Opal by Nuvia Hotel",
        "Hotel Villa Bora",
        "Yunona",
        "Grand Hotel Nirvana",
        "Biato Bahami Residence",
        "Izola Paradise",
        "Aqua Nevis Club Hotel",
        "Holiday Garden Club",
        "Apartment in Holiday Fort Golf Club",
        "Nessebar Fort Club",
        "Sweet Homes 7",
        "Emerald Paradise",
        "Hotel Breeze",
    ],
    "FLOWER STREET MAIN BUS STOP": [
        "Barcelo Royal Beach",
        "MPM Hotel Astoria",
        "Hotel Dune",
        "Mercury Hotel",
        "Four Points by Sheraton",
        "Hotel Venera",
        "Zornica Residence",
        "Menada Zornitsa Apartments",
        "Hotel Avenue",
        "Hotel Diamond",
        "Asteria Family Sunny Beach",
        "Sun Palace",
        "Central Plaza",
        "Family Hotel Romantik",
        "Family Hotel Magnolia",
        "Alba Sunny Beach",
        "Hotel Kuban",
        "Hotel Boulevard Sunny Beach",
    ],
    "BEST WESTERN / SVESHEST": [
        "Best Western Plus Premium Inn",
        "Melia Sunny Beach",
        "Sentido Neptun Beach",
        "MPM Hotel Kalina Garden",
        "Yavor Palace",
        "Hotel Laguna Park and Aqua Club",
        "Hotel Olymp",
        "Hotel Caesar Palace",
        "Admiral Plaza Hotel",
        "Hotel Planeta",
        "Flores Park Apart Hotel",
        "Mena Palace",
        "Hrizantema Hotel",
        "Complex Blue Summer",
    ],
    "ROYAL SUN / ARDA BUS STOP": [
        "Hotel Trakia Plaza",
        "Trakia Garden",
        "Hotel Baykal",
        "Hotel Pliska",
        "Hotel Pomorie Sun",
        "Europe Hotel Casino",
        "Hotel Meridian",
        "Hotel Dunav",
        "Tia Maria",
        "Harmony Palace",
        "Hotel Passat",
        "Aphrodite Gardens",
        "Complex Royal Sun",
        "Abelia Residence",
        "Apart Hotel Avalon",
        "Venera Palace",
        "Silver Springs",
        "Aparthotel CotD'Azure",
        "Tarsis Hotel",
        "Sea Breeze",
    ],
    "BLACK SEA HOTEL BUS STOP": [
        "Park Hotel Continental",
        "Hotel Tiara Beach",
        "Hotel Burgas Beach",
        "Nesebar Beach Hotel",
        "Golden Rainbow VIP Residence",
        "Golden Beach",
        "Hotel Longoza",
        "Hotel Golden Dune",
        "VIP Zone Apartments",
        "Hotel Cantilena",
        "Sunny Home 2",
    ],
    "BELLEVILLE / CACAO BUS STOP": [
        "River Park",
        "Hotel Zaara",
        "Hotel Regata Palace",
        "Casa del Sol",
        "Sun City 3 Apartments",
        "APARTELLO Rainbow 3",
        "Menada Rainbow Apartments",
        "Holiday Complex Rainbow",
        "ELITE 4 Sunny Beach",
        "Sunny View Central",
        "Hotel Sirena",
        "Hotel Fregata",
    ],
    "FOOTBALL STADIUM BUS STOP": [
        "Hotel Kalipso",
        "Hotel Nobel",
        "Galeon Residence",
        "Sunny Beach Club Adults Only",
        "Hotel Grenada",
        "Hotel and Spa Diamant Residence",
        "Imperial Resort",
        "Esperanto",
        "Hotel Zefir",
        "Hotel Kotva",
    ],
    "AQUA PARADISE HOTEL - WITH MINIBUS": [
        "Aqua Paradise Hotel",
    ],
    "SOL NESSEBAR PALAS - WITH MINIBUS": [
        "Sol Nessebar Palace",
        "Sol Nessebar Mare",
        "Sol Nessebar Bay",
    ],
    "FESTA PANORAMA NESS BUS STOP": [
        "Festa Panorama Hotel",
        "Paradiso Aparthotel",
    ],
    "PANTELEIMON BUS STOP - WITH MINIBUS": [
        "Apartment Rosa Marina",
        "Flowers Apartments",
        "DANY'S",
    ],
    "BILIYANA NESS - WITH MINIBUS": [
        "Perla Apartments",
        "Hotel Bilyana Beach",
        "MPM Hotel Arsena",
        "Aphrodite Beach Hotel",
        "Hotel Estrea",
    ],
    "OASIS NESS - WITH MINIBUS": [
        "Hotel Mirage",
    ],
    "MARINA PALAS - WITH MINIBUS": [
        "Hotel Marina Palace Affiliated by Melia",
        "Valencia Gardens",
        "VV VIGO Apartments",
    ],
}


@dataclass
class ImportStats:
    added: int = 0
    updated: int = 0


def _normalized(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()
    return re.sub(r"\s+", " ", cleaned)


def _split_aliases(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _merge_aliases(*alias_groups: list[str]) -> str:
    merged: list[str] = []
    seen: set[str] = set()
    for group in alias_groups:
        for alias in group:
            lowered = alias.lower()
            if alias and lowered not in seen:
                seen.add(lowered)
                merged.append(alias)
    return ",".join(merged)


def _generated_aliases(name: str) -> list[str]:
    aliases = [name]
    patterns = [
        ("MPM Hotel ", lambda rest: [rest, f"MPM {rest}"]),
        ("DIT ", lambda rest: [rest, f"DIT {rest}"]),
        ("Apart Hotel ", lambda rest: [rest]),
        ("Aparthotel ", lambda rest: [rest]),
        ("Family Hotel ", lambda rest: [rest]),
        ("Hotel and Spa ", lambda rest: [rest]),
        ("Hotel ", lambda rest: [rest]),
        ("Complex ", lambda rest: [rest]),
    ]
    for prefix, builder in patterns:
        if name.startswith(prefix):
            aliases.extend(builder(name[len(prefix):].strip()))
            break
    return [alias for alias in aliases if alias]


def _candidate_texts(hotel: Hotel) -> list[str]:
    return [hotel.name, *_split_aliases(hotel.aliases)]


def _find_existing_hotel(hotels: list[Hotel], target_name: str) -> Hotel | None:
    target_normalized = _normalized(target_name)
    for hotel in hotels:
        if _normalized(hotel.name) == target_normalized:
            return hotel
        if any(_normalized(alias) == target_normalized for alias in _split_aliases(hotel.aliases)):
            return hotel

    best_hotel: Hotel | None = None
    best_score = 0.0
    for hotel in hotels:
        score = max(
            fuzz.token_set_ratio(target_normalized, _normalized(candidate))
            for candidate in _candidate_texts(hotel)
            if candidate
        )
        if score > best_score:
            best_score = score
            best_hotel = hotel
    return best_hotel if best_hotel and best_score >= 94 else None


def import_official_mapping() -> tuple[ImportStats, int]:
    init_db()
    stats = ImportStats()
    with session_scope() as db:
        city = db.query(City).filter(City.name == SUNNY_BEACH_CITY).first()
        if not city:
            raise ValueError(f"City {SUNNY_BEACH_CITY!r} not found.")

        stops = {
            stop.name: stop
            for stop in db.query(BusStop).filter(BusStop.city_id == city.id).all()
        }
        hotels = db.query(Hotel).all()

        for official_stop_name, hotel_names in OFFICIAL_MAPPING.items():
            db_stop_name = STOP_NAME_MAP[official_stop_name]
            stop = stops.get(db_stop_name)
            if not stop:
                raise ValueError(f"Bus stop {db_stop_name!r} not found.")

            for hotel_name in hotel_names:
                existing = _find_existing_hotel(hotels, hotel_name)
                alias_list = _generated_aliases(hotel_name)
                if existing:
                    existing.aliases = _merge_aliases(_split_aliases(existing.aliases), alias_list)
                    existing.bus_stop_id = stop.id
                    existing.city_id = city.id
                    stats.updated += 1
                    continue

                hotel = Hotel(
                    name=hotel_name,
                    aliases=_merge_aliases(alias_list),
                    bus_stop_id=stop.id,
                    city_id=city.id,
                )
                db.add(hotel)
                hotels.append(hotel)
                stats.added += 1

        db.flush()
        sunny_beach_total = db.query(Hotel).filter(Hotel.city_id == city.id).count()
    return stats, sunny_beach_total


if __name__ == "__main__":
    stats, total = import_official_mapping()
    print(f"Total hotels added: {stats.added}")
    print(f"Total hotels updated: {stats.updated}")
    print(f"Total hotels now in Sunny Beach: {total}")
