from __future__ import annotations

import unittest

from cruise_email_dashboard.database.db import SessionLocal
from cruise_email_dashboard.database.models import BusStop, City, Hotel, VehicleType
from cruise_email_dashboard.services.classifier import classify_email


TARGET_CITY = "Sunny Beach"
TARGET_STOP = "Hotel Best Western / Sveshest"
TARGET_HOTEL = "Best Western / Sveshest"
BASE_ALIASES = "Best Western,Sveshest,AluaSoul Sunny Beach,AluaSoul"
COMMERCIAL_WARNING = (
    "Booking references Spiders Pub which is not a hotel. "
    "Customer may have entered wrong hotel name. Manual assignment required."
)


def ensure_best_western_setup(*, aliases: str) -> None:
    with SessionLocal() as db:
        city = db.query(City).filter(City.name == TARGET_CITY).first()
        if not city:
            city = City(name=TARGET_CITY, local_name=TARGET_CITY, timezone="Europe/Sofia", aliases="sunny beach")
            db.add(city)
            db.flush()

        stop = db.query(BusStop).filter(BusStop.name == TARGET_STOP).first()
        if not stop:
            stop = BusStop(
                name=TARGET_STOP,
                address=TARGET_STOP,
                latitude=42.6928,
                longitude=27.7038,
                city_id=city.id,
                maps_url="https://www.google.com/maps?q=42.6928,27.7038",
                description="test Best Western stop",
                vehicle_type=VehicleType.doubledecker,
            )
            db.add(stop)
            db.flush()
        else:
            stop.city_id = city.id
            stop.address = TARGET_STOP
            stop.vehicle_type = VehicleType.doubledecker

        hotel = db.query(Hotel).filter(Hotel.name == TARGET_HOTEL).first()
        if not hotel:
            hotel = Hotel(
                name=TARGET_HOTEL,
                aliases=aliases,
                city_id=city.id,
                bus_stop_id=stop.id,
            )
            db.add(hotel)
        else:
            hotel.aliases = aliases
            hotel.city_id = city.id
            hotel.bus_stop_id = stop.id

        db.commit()


def classify_spiders_pub_booking():
    body = "\n".join(
        [
            "You have just received a new booking!",
            "Hotel or complex: Spiders Pub",
            "Participants: 2 adults",
            "Date: 24 July 2026",
            "Time: 09:00",
        ]
    )
    with SessionLocal() as db:
        return classify_email(
            db,
            subject="Morning VIP Catamaran Booking Confirmation",
            body=body,
            html_body="",
            threshold=80,
            fallback_sender="customer@example.com",
            fallback_name="Test Guest",
        )


class CommercialVenueFlagTests(unittest.TestCase):
    def test_spiders_pub_alias_match_wins_over_commercial_venue_flag(self) -> None:
        ensure_best_western_setup(aliases=f"{BASE_ALIASES},Spiders Pub,Spider's Pub")

        result = classify_spiders_pub_booking()

        self.assertIsNotNone(result.matched_hotel)
        self.assertEqual(result.matched_hotel.name, TARGET_HOTEL)
        self.assertEqual(result.resolved_status.value, "pending")
        self.assertNotIn(COMMERCIAL_WARNING, result.warning_note)

    def test_spiders_pub_without_alias_still_triggers_manual_assignment_warning(self) -> None:
        ensure_best_western_setup(aliases=BASE_ALIASES)

        result = classify_spiders_pub_booking()

        self.assertIsNone(result.matched_hotel)
        self.assertEqual(result.resolved_status.value, "flagged")
        self.assertIn(COMMERCIAL_WARNING, result.warning_note)


if __name__ == "__main__":
    unittest.main()
