from __future__ import annotations

import os
import tempfile
from datetime import date, datetime, time
from pathlib import Path

TEST_DATABASE_PATH = Path(tempfile.gettempdir()) / f"vip-catamaran-pytest-{os.getpid()}.db"
TEST_DATABASE_URL = f"sqlite:///{TEST_DATABASE_PATH.as_posix()}"


def _bootstrap_test_environment() -> None:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    os.environ.setdefault("IMAP_HOST", "test-imap.local")
    os.environ.setdefault("IMAP_USER", "test-user")
    os.environ.setdefault("IMAP_PASSWORD", "test-pass")
    os.environ.setdefault("SMTP_HOST", "test-smtp.local")
    os.environ.setdefault("SMTP_USER", "test-user")
    os.environ.setdefault("SMTP_PASSWORD", "test-pass")
    os.environ.setdefault("SECRET_KEY", "test-secret-key")


_bootstrap_test_environment()

from cruise_email_dashboard.database.db import DATABASE_URL, SessionLocal, engine, init_db
from cruise_email_dashboard.database.models import BusStop, City, EmailLog, EmailStatus, Hotel, User, UserRole, VehicleType
from cruise_email_dashboard.services.auth import hash_password


def _sqlite_path() -> Path | None:
    if not DATABASE_URL.startswith("sqlite:///"):
        return None
    raw_path = DATABASE_URL.removeprefix("sqlite:///")
    return Path(raw_path)


def _reset_ci_sqlite_db() -> None:
    db_path = _sqlite_path()
    if db_path is None:
        return
    if db_path != TEST_DATABASE_PATH:
        return
    engine.dispose()
    if db_path.exists():
        db_path.unlink()


def _ensure_user(db, username: str, password: str, role: UserRole) -> None:
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        existing.hashed_password = hash_password(password)
        existing.role = role
        return
    db.add(User(username=username, hashed_password=hash_password(password), role=role))


def _ensure_city(db, name: str) -> City:
    city = db.query(City).filter(City.name == name).first()
    if city:
        return city
    city = City(name=name, local_name=name, timezone="Europe/Sofia", aliases=name.lower())
    db.add(city)
    db.flush()
    return city


def _ensure_stop(
    db,
    *,
    city_id: int,
    name: str,
    address: str,
    latitude: float,
    longitude: float,
    description: str,
) -> BusStop:
    stop = db.query(BusStop).filter(BusStop.name == name).first()
    if stop:
        stop.city_id = city_id
        stop.address = address
        stop.latitude = latitude
        stop.longitude = longitude
        stop.description = description
        stop.maps_url = f"https://www.google.com/maps?q={latitude},{longitude}"
        stop.vehicle_type = VehicleType.doubledecker
        return stop
    stop = BusStop(
        name=name,
        address=address,
        latitude=latitude,
        longitude=longitude,
        city_id=city_id,
        maps_url=f"https://www.google.com/maps?q={latitude},{longitude}",
        description=description,
        vehicle_type=VehicleType.doubledecker,
    )
    db.add(stop)
    db.flush()
    return stop


def _ensure_hotel(db, *, city_id: int, bus_stop_id: int, name: str, aliases: str) -> Hotel:
    hotel = db.query(Hotel).filter(Hotel.name == name).first()
    if hotel:
        hotel.city_id = city_id
        hotel.bus_stop_id = bus_stop_id
        hotel.aliases = aliases
        return hotel
    hotel = Hotel(name=name, aliases=aliases, city_id=city_id, bus_stop_id=bus_stop_id)
    db.add(hotel)
    db.flush()
    return hotel


def _ensure_email(db, *, hotel: Hotel, stop: BusStop) -> None:
    existing = db.query(EmailLog).filter(EmailLog.message_id == "<ci-bootstrap-email@vipcatamaran.local>").first()
    if existing:
        return
    db.add(
        EmailLog(
            message_id="<ci-bootstrap-email@vipcatamaran.local>",
            received_at=datetime(2026, 6, 18, 10, 0, 0),
            sender_email="customer@example.com",
            sender_name="CI Test Guest",
            subject="Morning VIP Catamaran Booking Confirmation",
            body_snippet="CI bootstrap booking",
            full_body="CI bootstrap booking body",
            detected_language="en",
            template_language="en",
            detected_hotel_id=hotel.id,
            assigned_bus_stop_id=stop.id,
            booking_type="MORNING",
            cruise_date=date(2026, 6, 19),
            cruise_time=time(9, 0),
            num_adults=2,
            num_children=0,
            customer_phone="+359000000000",
            booking_number="CI-BOOTSTRAP-1",
            gyg_ref="CIREF123",
            total_price="100 EUR",
            detected_city="Sunny Beach",
            raw_customer_name_extraction="CI Test Guest",
            raw_hotel_extraction=hotel.name,
            extraction_source="ci_bootstrap",
            pickup_time_text="08:30",
            draft_reply="CI bootstrap draft",
            status=EmailStatus.pending,
            warning_note="",
            is_new=True,
        )
    )


def pytest_sessionstart(session) -> None:
    _reset_ci_sqlite_db()
    init_db()

    with SessionLocal() as db:
        _ensure_user(db, "admin", "admin123", UserRole.admin)
        _ensure_user(db, "staff", "staff123", UserRole.staff)
        _ensure_user(db, "tickets", "Vessy@02", UserRole.staff)
        _ensure_user(db, "bookings", "Olga@02", UserRole.staff)
        _ensure_user(db, "info", "Teddy@02", UserRole.staff)

        sunny_beach = _ensure_city(db, "Sunny Beach")
        flower_street = _ensure_stop(
            db,
            city_id=sunny_beach.id,
            name="Flower Street Main Bus Stop",
            address="Flower Street, Sunny Beach",
            latitude=42.6945,
            longitude=27.7060,
            description="CI bootstrap Flower Street stop",
        )
        palm_court = _ensure_stop(
            db,
            city_id=sunny_beach.id,
            name="Palm Court Bus Stop",
            address="Palm Court, Sunny Beach",
            latitude=42.6992,
            longitude=27.7128,
            description="CI bootstrap Palm Court stop",
        )
        hotel = _ensure_hotel(
            db,
            city_id=sunny_beach.id,
            bus_stop_id=flower_street.id,
            name="CI Bootstrap Hotel",
            aliases="CI Hotel,Bootstrap Hotel",
        )
        _ensure_hotel(
            db,
            city_id=sunny_beach.id,
            bus_stop_id=palm_court.id,
            name="Codex HM Test Existing",
            aliases="Existing Alias",
        )
        _ensure_email(db, hotel=hotel, stop=flower_street)
        db.commit()


def pytest_sessionfinish(session, exitstatus) -> None:
    db_path = _sqlite_path()
    if db_path is None or db_path != TEST_DATABASE_PATH:
        return
    engine.dispose()
    if db_path.exists():
        db_path.unlink()
