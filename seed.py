from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from cruise_email_dashboard.database.db import Base, engine, init_db, session_scope
from cruise_email_dashboard.database.models import BusStop, City, EmailLog, EmailStatus, Hotel, Schedule, User, UserRole, VehicleType
from cruise_email_dashboard.services.auth import hash_password
from cruise_email_dashboard.services.reply_generator import MISSING_PICKUP_TIME_PLACEHOLDER, regenerate_email_draft
from cruise_email_dashboard.services.scheduler import resolve_pickup_schedule


def sunny_beach_data():
    # Maps links use https://www.google.com/maps?q=LAT,LNG — permanent, no URL shortener.
    # Coordinates verified against the E87 main road corridor through Sunny Beach.
    # Aqua Paradise coords corrected to 42.6551,27.6823 (official GPS from aquaparadiseresort.bg).
    # SOL Nessebar Palas coords corrected to 42.6520,27.6870 (2.5 km south of Nessebar old town, beachfront).
    return [
        ("Vlas - Petrol Station",               "Sveti Vlas main road stop",              42.7130, 27.7580, "https://www.google.com/maps?q=42.7130,27.7580", "the main road stop by the petrol station in Sveti Vlas",          VehicleType.doubledecker, "08:20", "13:30", "18:20", "09:20", "11:15", "16:50"),
        ("Mercury Grand Market",                 "Mercury Grand Market, Sunny Beach",       42.7088, 27.7300, "https://www.google.com/maps?q=42.7088,27.7300", "the bus stop on the main road by Mercury Grand Market",           VehicleType.doubledecker, "08:20", "13:30", "18:20", "09:20", "11:15", "16:50"),
        ("Secrets Resort - Main Road Bus Stop",  "Secrets Resort main road stop",           42.7068, 27.7248, "https://www.google.com/maps?q=42.7068,27.7248", "the main road bus stop outside Secrets Resort",                   VehicleType.doubledecker, "08:20", "13:30", "18:25", "09:20", "11:20", "16:55"),
        ("Helena / Zora - Main Road Bus Stop",   "Helena / Zora main road stop",            42.7038, 27.7195, "https://www.google.com/maps?q=42.7038,27.7195", "the main road stop serving Helena and Zora",                      VehicleType.doubledecker, "08:25", "13:40", "18:25", "09:25", "11:20", "16:55"),
        ("Efir Bus Stop",                        "Efir main road stop",                     42.7010, 27.7160, "https://www.google.com/maps?q=42.7010,27.7160", "the main road stop at Efir",                                      VehicleType.doubledecker, "08:30", "13:40", "18:30", "09:30", "11:30", "17:00"),
        ("Palm Court Bus Stop",                  "Palm Court main road stop",               42.6992, 27.7128, "https://www.google.com/maps?q=42.6992,27.7128", "the main road stop near Palm Court",                              VehicleType.doubledecker, "08:30", "13:40", "18:30", "09:30", "11:30", "17:00"),
        ("Opal Bus Stop",                        "Opal main road stop",                     42.6975, 27.7095, "https://www.google.com/maps?q=42.6975,27.7095", "the main road stop at Opal",                                      VehicleType.doubledecker, "08:30", "13:50", "18:30", "09:30", "11:30", "17:00"),
        ("Flower Street Main Bus Stop",          "Flower Street, Sunny Beach",              42.6945, 27.7060, "https://www.google.com/maps?q=42.6945,27.7060", "the main road bus stop by Flower Street",                         VehicleType.doubledecker, "08:35", "13:50", "18:35", "09:35", "11:35", "17:05"),
        ("Hotel Best Western / Sveshest",        "Best Western / Sveshest main road stop",  42.6928, 27.7038, "https://www.google.com/maps?q=42.6928,27.7038", "the main road stop next to Best Western / Sveshest",              VehicleType.doubledecker, "08:35", "13:50", "18:35", "09:35", "11:35", "17:05"),
        ("Royal Sun / Arda Bus Stop",            "Royal Sun / Arda main road stop",         42.6900, 27.7012, "https://www.google.com/maps?q=42.6900,27.7012", "the main road stop for Royal Sun and Arda",                       VehicleType.doubledecker, "08:40", "14:00", "18:40", "09:40", "11:40", "17:10"),
        ("Black Sea Hotel Bus Stop",             "Black Sea Hotel main road stop",          42.6885, 27.6990, "https://www.google.com/maps?q=42.6885,27.6990", "the main road stop at Black Sea Hotel",                           VehicleType.doubledecker, "08:40", "14:00", "18:40", "09:40", "11:40", "17:10"),
        ("Belleville / Cacao Bus Stop",          "Belleville / Cacao main road stop",       42.6860, 27.6970, "https://www.google.com/maps?q=42.6860,27.6970", "the main road stop for Belleville and Cacao",                     VehicleType.doubledecker, "08:45", "14:00", "18:45", "09:45", "11:45", "17:15"),
        ("Football Stadium Bus Stop",            "Nessebar football stadium stop",          42.6840, 27.6952, "https://www.google.com/maps?q=42.6840,27.6952", "the main road bus stop by the football stadium",                  VehicleType.doubledecker, "08:45", "14:10", "18:45", "09:45", "11:45", "17:15"),
        ("Festa Panorama Ness Bus Stop",         "Festa Panorama stop",                     42.6822, 27.6938, "https://www.google.com/maps?q=42.6822,27.6938", "the stop by Festa Panorama in Nessebar",                          VehicleType.doubledecker, "08:50", "14:15", "18:50", "09:50", "11:50", "17:20"),
        # Minibus stops — south of Nessebar, corrected coords from official hotel GPS sources
        ("Aqua Paradise Hotel - with Minibus",   "Aqua Paradise Hotel",                     42.6551, 27.6823, "https://www.google.com/maps?q=42.6551,27.6823", "the hotel entrance at Aqua Paradise",                             VehicleType.minibus,      "08:40", "14:10", "18:40", "09:36", "11:40", "17:10"),
        ("SOL Nessebar Palas - with Minibus",    "SOL Nessebar Palace",                     42.6520, 27.6870, "https://www.google.com/maps?q=42.6520,27.6870", "the entrance area at SOL Nessebar Palas",                         VehicleType.minibus,      "08:40", "14:10", "18:40", "09:40", "11:40", "17:10"),
        ("Panteleimon Bus Stop - with Minibus",  "Panteleimon stop",                        42.6670, 27.7090, "https://www.google.com/maps?q=42.6670,27.7090", "the minibus stop by Panteleimon",                                 VehicleType.minibus,      "08:40", "14:15", "18:45", "09:40", "11:40", "17:10"),
        ("Biliyana Ness - with Minibus",         "Biliyana stop",                           42.6652, 27.7110, "https://www.google.com/maps?q=42.6652,27.7110", "the minibus stop by Biliyana",                                    VehicleType.minibus,      "08:45", "14:15", "18:45", "09:45", "11:45", "17:15"),
        ("Oasis Ness - with Minibus",            "Oasis Nessebar",                          42.6635, 27.7132, "https://www.google.com/maps?q=42.6635,27.7132", "the minibus stop by Oasis Nessebar",                              VehicleType.minibus,      "08:45", "14:15", "18:45", "09:45", "11:45", "17:15"),
        ("Marina Palas - with Minibus",          "Marina Palace",                           42.6618, 27.7158, "https://www.google.com/maps?q=42.6618,27.7158", "the minibus stop at Marina Palas",                                VehicleType.minibus,      "08:50", "14:20", "18:50", "09:50", "11:45", "17:15"),
        ("Meet at Catamaran",                    "Nessebar old town catamaran meeting point",42.6595, 27.7210, "https://www.google.com/maps?q=42.6595,27.7210", "the catamaran boarding point",                                    VehicleType.minibus,      "08:55", "14:25", "18:55", "09:55", "11:50", "17:20"),
    ]


def seed() -> None:
    Base.metadata.drop_all(bind=engine)
    init_db()

    with session_scope() as db:
        sunny_beach = City(name="Sunny Beach", local_name="Слънчев бряг", timezone="Europe/Sofia", aliases="sunny beach,slanchev bryag,slunchev bryag,sunnybeach")
        obzor       = City(name="Obzor",        local_name="Обзор",        timezone="Europe/Sofia", aliases="obzor,обзор")
        pomorie     = City(name="Pomorie",       local_name="Поморие",      timezone="Europe/Sofia", aliases="pomorie,поморие,pomori")
        db.add_all([sunny_beach, obzor, pomorie])
        db.flush()

        stops_by_name: dict[str, BusStop] = {}

        for item in sunny_beach_data():
            name, address, lat, lng, maps_url, description, vehicle_type, morning, afternoon, sunset, anastasia, september_day, september_sunset = item
            stop = BusStop(
                name=name,
                address=address,
                latitude=lat,
                longitude=lng,
                city_id=sunny_beach.id,
                maps_url=maps_url,
                description=description,
                vehicle_type=vehicle_type,
            )
            db.add(stop)
            db.flush()
            stops_by_name[name] = stop
            db.add_all([
                Schedule(bus_stop_id=stop.id, pickup_time=time.fromisoformat(morning),          season_label="morning"),
                Schedule(bus_stop_id=stop.id, pickup_time=time.fromisoformat(afternoon),        season_label="afternoon"),
                Schedule(bus_stop_id=stop.id, pickup_time=time.fromisoformat(sunset),           season_label="sunset"),
                Schedule(bus_stop_id=stop.id, pickup_time=time.fromisoformat(anastasia),        season_label="anastasia"),
                Schedule(bus_stop_id=stop.id, pickup_time=time.fromisoformat(september_day),    season_label="september_day"),
                Schedule(bus_stop_id=stop.id, pickup_time=time.fromisoformat(september_sunset), season_label="september_sunset"),
            ])

        sunny_hotels = [
            ("Helena Park",          "Helena, Zora, The Helena Park hotel",        "Helena / Zora - Main Road Bus Stop"),
            ("Best Western / Sveshest", "Best Western,Sveshest,AluaSoul Sunny Beach,AluaSoul", "Hotel Best Western / Sveshest"),
            ("Royal Sun / Arda",     "Royal Sun,Arda",                             "Royal Sun / Arda Bus Stop"),
            ("Black Sea Hotel",      "Black Sea",                                  "Black Sea Hotel Bus Stop"),
            ("Belleville / Cacao",   "Belleville,Cacao",                           "Belleville / Cacao Bus Stop"),
            ("Aqua Paradise Hotel",  "Aqua Paradise",                              "Aqua Paradise Hotel - with Minibus"),
            ("SOL Nessebar Palas",   "SOL Nessebar,Nessebar Palas",                "SOL Nessebar Palas - with Minibus"),
            ("Panteleimon",          "Panteleimon",                                "Panteleimon Bus Stop - with Minibus"),
            ("Biliyana Ness",        "Biliyana",                                   "Biliyana Ness - with Minibus"),
            ("Oasis Ness",           "Oasis",                                      "Oasis Ness - with Minibus"),
            ("Marina Palas",         "Marina Palas",                               "Marina Palas - with Minibus"),
            ("Secrets Resort",       "Secrets Resort",                             "Secrets Resort - Main Road Bus Stop"),
        ]
        for name, aliases, stop_name in sunny_hotels:
            db.add(Hotel(name=name, aliases=aliases, bus_stop_id=stops_by_name[stop_name].id, city_id=sunny_beach.id))

        # Obzor stops — coords are reasonable estimates for the resort strip north of Obzor town.
        # Maps links are coordinate-based (permanent). Update coords if staff can verify on-site.
        obzor_stops = {
            "Sunrise All Suite Resort": ("Sunrise All Suite Resort", 42.8150, 27.8800, "https://www.google.com/maps?q=42.8150,27.8800", "outside Sunrise All Suite Resort",              VehicleType.guide, "09:50"),
            "Sol Luna Bay":             ("Sol Luna Bay",             42.8200, 27.8850, "https://www.google.com/maps?q=42.8200,27.8850", "outside Sol Luna Bay",                          VehicleType.guide, "10:00"),
            "Clubhotel Miramar":        ("Clubhotel Miramar",        42.8170, 27.8950, "https://www.google.com/maps?q=42.8170,27.8950", "outside Clubhotel Miramar",                     VehicleType.guide, "10:15"),
            "Helios Bay":               ("Helios Bay",               42.8135, 27.8990, "https://www.google.com/maps?q=42.8135,27.8990", "outside Helios Bay",                            VehicleType.guide, "10:25"),
            "Central Bus Station":      ("Central Bus Station",      42.8195, 27.8775, "https://www.google.com/maps?q=42.8195,27.8775", "at the Central Bus Station on the main road",   VehicleType.guide, "10:30"),
            "Luk Oil Petrol Station":   ("Luk Oil Petrol Station",   42.8212, 27.8720, "https://www.google.com/maps?q=42.8212,27.8720", "outside Luk Oil Petrol Station",                VehicleType.guide, "10:30"),
        }
        for stop_name, (address, lat, lng, maps_url, description, vehicle_type, pickup) in obzor_stops.items():
            stop = BusStop(
                name=stop_name,
                address=address,
                latitude=lat,
                longitude=lng,
                city_id=obzor.id,
                maps_url=maps_url,
                description=description,
                vehicle_type=vehicle_type,
            )
            db.add(stop)
            db.flush()
            stops_by_name[stop_name] = stop
            db.add(Schedule(bus_stop_id=stop.id, pickup_time=time.fromisoformat(pickup), season_label="default"))

        obzor_hotels = [
            ("Sunrise All Suite Resort",   "Sunrise",              "Sunrise All Suite Resort"),
            ("Sol Luna Bay",               "Sol Luna",             "Sol Luna Bay"),
            ("Obzor Beach Resort",         "Obzor Beach Resort",   "Clubhotel Miramar"),
            ("Clubhotel Miramar",          "Miramar",              "Clubhotel Miramar"),
            ("Casablanca Hotel",           "Casablanca",           "Helios Bay"),
            ("Helios Bay",                 "Helios",               "Helios Bay"),
            ("Helios Beach",               "Helios Beach,Helios",  "Helios Bay"),
            ("Central Bus Station (Main Rd)", "Central Bus Station", "Central Bus Station"),
            ("Luk Oil Petrol Station",     "Luk Oil,Lukoil",       "Luk Oil Petrol Station"),
        ]
        for name, aliases, stop_name in obzor_hotels:
            db.add(Hotel(name=name, aliases=aliases, bus_stop_id=stops_by_name[stop_name].id, city_id=obzor.id))

        # Pomorie stops — corrected coordinates and links.
        # Sunset Resort: corrected to 42.5635,27.6042 (verified via mouzenidis.com / travelmyth.com).
        # Hotel Wave: kept at 42.5730,27.6080 — located north of main Pomorie on the coast, plausible.
        # "Hotel Aqua Paradise" at 42.6705,27.6990 removed — this is not in Pomorie,
        #   it is the Nessebar Aqua Paradise. A Pomorie pickup at that location makes no sense.
        #   If VIP Catamaran does serve that hotel from a Pomorie-area route, re-add with correct city_id.
        pomorie_rows = [
            ("Saint George",      "Saint George",  "Saint George",      42.5560, 27.6360, "https://www.google.com/maps?q=42.5560,27.6360", "outside Saint George",      "08:05"),
            ("Hotel Grand Pomori","Grand Pomori",  "Hotel Grand Pomori", 42.5575, 27.6295, "https://www.google.com/maps?q=42.5575,27.6295", "outside Hotel Grand Pomori","08:10"),
            ("Sunset Resort",     "Sunset Resort", "Sunset Resort",      42.5635, 27.6042, "https://www.google.com/maps?q=42.5635,27.6042", "outside Sunset Resort",     "08:15"),
            ("Hotel Wave",        "Wave",          "Hotel Wave",         42.5730, 27.6080, "https://www.google.com/maps?q=42.5730,27.6080", "outside Hotel Wave",        "08:35"),
        ]
        for hotel_name, aliases, stop_name, lat, lng, maps_url, description, pickup in pomorie_rows:
            stop = BusStop(
                name=stop_name,
                address=stop_name,
                latitude=lat,
                longitude=lng,
                city_id=pomorie.id,
                maps_url=maps_url,
                description=description,
                vehicle_type=VehicleType.minibus,
            )
            db.add(stop)
            db.flush()
            stops_by_name[stop_name] = stop
            db.add(Schedule(bus_stop_id=stop.id, pickup_time=time.fromisoformat(pickup), season_label="tuesday_friday_morning", valid_days="1,4"))
            db.add(Hotel(name=hotel_name, aliases=aliases, bus_stop_id=stop.id, city_id=pomorie.id))

        if not db.query(User).filter(User.username == "presadmin").first():
            db.add(User(username="presadmin", hashed_password=hash_password("presko06"), role=UserRole.admin))
        if not db.query(User).filter(User.username == "staff").first():
            db.add(User(username="staff", hashed_password=hash_password("staff123"), role=UserRole.staff))
        db.flush()

        emails = [
            {
                "subject": "Morning VIP Catamaran Booking Confirmation",
                "sender_email": "customer-sunnybeach@reply.getyourguide.com",
                "sender_name": "William James",
                "detected_hotel": db.query(Hotel).filter(Hotel.name == "Helena Park").first(),
                "booking_type": "MORNING",
                "cruise_date": date(2026, 6, 21),
                "cruise_time": time(9, 0),
                "num_adults": 2,
                "booking_number": "GYG-SB-1001",
                "gyg_ref": "GYGBLHQKWF67",
                "total_price": "170 EUR",
                "customer_phone": "+447700900111",
                "detected_language": "en",
                "raw_customer_name_extraction": "William James",
                "raw_hotel_extraction": "Helena Park",
                "extraction_source": "notes_hotel_field",
                "status": EmailStatus.pending,
                "received_at": datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=3),
                "warning_note": "",
            },
            {
                "subject": "Obzor & Old Nessebar VIP Catamaran Booking Confirmation",
                "sender_email": "customer-obzor@reply.getyourguide.com",
                "sender_name": "Sofia Martin",
                "detected_hotel": db.query(Hotel).filter(Hotel.name == "Sunrise All Suite Resort").first(),
                "booking_type": "OBZOR",
                "cruise_date": date(2026, 7, 10),
                "cruise_time": time(10, 30),
                "num_adults": 4,
                "booking_number": "GYG-OB-2001",
                "gyg_ref": "GYGOBZ12345",
                "total_price": "320 EUR",
                "customer_phone": "+359888123456",
                "detected_language": "de",
                "raw_customer_name_extraction": "Sofia Martin",
                "raw_hotel_extraction": "Sunrise",
                "extraction_source": "options_field",
                "status": EmailStatus.sent,
                "received_at": datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1, hours=2),
                "warning_note": "",
            },
            {
                "subject": "Pomorie VIP Catamaran Booking Confirmation",
                "sender_email": "customer-pomorie@reply.getyourguide.com",
                "sender_name": "Elena Petrova",
                "detected_hotel": db.query(Hotel).filter(Hotel.name == "Saint George").first(),
                "booking_type": "POMORIE",
                "cruise_date": date(2026, 7, 8),
                "cruise_time": time(9, 0),
                "num_adults": 2,
                "booking_number": "GYG-PO-3001",
                "gyg_ref": "GYGPOM54321",
                "total_price": "150 EUR",
                "customer_phone": "+359887765432",
                "detected_language": "en",
                "raw_customer_name_extraction": "Elena Petrova",
                "raw_hotel_extraction": "Saint George",
                "extraction_source": "notes_hotel_field",
                "status": EmailStatus.flagged,
                "received_at": datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=7),
                "warning_note": "Pomorie pickups are Tuesday and Friday only. Please contact the customer to clarify their cruise date.",
            },
            {
                "subject": "Sunset Cruise - VIP Catamaran Booking Confirmation",
                "sender_email": "customer-manual@reply.getyourguide.com",
                "sender_name": "Maria Lopez",
                "detected_hotel": None,
                "booking_type": "SUNSET",
                "cruise_date": date(2026, 9, 3),
                "cruise_time": time(18, 30),
                "num_adults": 3,
                "booking_number": "GYG-SB-1002",
                "gyg_ref": "GYGSUNSET99",
                "total_price": "255 EUR",
                "customer_phone": "+34999999999",
                "detected_language": "es",
                "raw_customer_name_extraction": "Maria Lopez",
                "raw_hotel_extraction": "Spiders Pub",
                "extraction_source": "notes_freeform",
                "status": EmailStatus.manual,
                "received_at": datetime.now(UTC).replace(tzinfo=None) - timedelta(days=2),
                "warning_note": "Booking references Spiders Pub which is not a hotel. Customer may have entered wrong hotel name. Manual assignment required.",
            },
        ]

        for item in emails:
            detected_hotel = item["detected_hotel"]
            bus_stop = detected_hotel.bus_stop if detected_hotel else None
            email = EmailLog(
                message_id=f"<{item['booking_number']}@vipcatamaran.com>",
                received_at=item["received_at"],
                sender_email=item["sender_email"],
                sender_name=item["sender_name"],
                subject=item["subject"],
                body_snippet=f"Booking confirmation for {item['sender_name']}",
                full_body=f"Sample booking email for {item['sender_name']} staying at {item['raw_hotel_extraction']}.",
                detected_language=item["detected_language"],
                template_language=item["detected_language"],
                detected_hotel_id=detected_hotel.id if detected_hotel else None,
                assigned_bus_stop_id=bus_stop.id if bus_stop else None,
                booking_type=item["booking_type"],
                cruise_date=item["cruise_date"],
                cruise_time=item["cruise_time"],
                num_adults=item["num_adults"],
                customer_phone=item["customer_phone"],
                booking_number=item["booking_number"],
                gyg_ref=item["gyg_ref"],
                total_price=item["total_price"],
                raw_customer_name_extraction=item["raw_customer_name_extraction"],
                raw_hotel_extraction=item["raw_hotel_extraction"],
                extraction_source=item["extraction_source"],
                status=item["status"],
                is_new=item["status"] != EmailStatus.sent,
                warning_note=item["warning_note"],
                sent_at=(item["received_at"] + timedelta(minutes=25)) if item["status"] == EmailStatus.sent else None,
            )
            if bus_stop:
                resolution = resolve_pickup_schedule(db, bus_stop, email.booking_type, email.cruise_date)
                email.pickup_time_text = resolution.schedule.pickup_time.strftime("%H:%M") if resolution.schedule else MISSING_PICKUP_TIME_PLACEHOLDER
                email.warning_note = "\n".join(part for part in [email.warning_note, resolution.warning_note] if part).strip()
            regenerate_email_draft(email)
            db.add(email)

    print("Seed complete. Demo users: presadmin/presko06 and staff/staff123")


if __name__ == "__main__":
    seed()
