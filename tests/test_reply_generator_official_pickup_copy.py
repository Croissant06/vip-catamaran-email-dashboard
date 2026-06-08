from __future__ import annotations

import unittest
from datetime import date

from cruise_email_dashboard.database.models import BusStop, City, EmailLog, Hotel, VehicleType
from cruise_email_dashboard.services.reply_generator import build_reply


def make_email(
    *,
    stop_name: str,
    stop_description: str,
    vehicle_type: VehicleType,
    language: str = "en",
    pickup_time: str = "08:20",
) -> EmailLog:
    city = City(name="Sunny Beach")
    stop = BusStop(
        name=stop_name,
        address=stop_name,
        latitude=42.0,
        longitude=27.0,
        maps_url="https://example.com/map",
        description=stop_description,
        vehicle_type=vehicle_type,
    )
    stop.city = city
    hotel = Hotel(name="Helena Park", aliases="Helena")
    hotel.bus_stop = stop
    hotel.bus_stop_id = 1

    email = EmailLog(
        received_at=date(2026, 6, 8),
        sender_email="guest@example.com",
        sender_name="Test Guest",
        subject="Booking Confirmation",
        full_body="Body",
        detected_language=language,
        template_language=language,
        booking_type="MORNING",
        cruise_date=date(2026, 6, 10),
        num_adults=2,
        pickup_time_text=pickup_time,
        raw_hotel_extraction=hotel.name,
    )
    email.assigned_bus_stop = stop
    email.assigned_bus_stop_id = 1
    email.detected_hotel = hotel
    email.detected_hotel_id = 1
    return email


class OfficialPickupCopyTests(unittest.TestCase):
    def test_english_doubledecker_stop_uses_official_vlas_wording(self) -> None:
        email = make_email(
            stop_name="Vlas - Petrol Station",
            stop_description="legacy",
            vehicle_type=VehicleType.doubledecker,
            language="en",
            pickup_time="08:20",
        )

        reply, _, _ = build_reply(email)

        self.assertIn(
            'Please find attached a link to the pickup point that you have selected. It is the bus stop on the main road at the roundabout next to the petrol station in Sveti Vlas. Our big red London double-decker bus will be there at 08:20 to collect you.',
            reply,
        )

    def test_english_minibus_stop_uses_official_aqua_paradise_wording(self) -> None:
        email = make_email(
            stop_name="Aqua Paradise Hotel - with Minibus",
            stop_description="legacy",
            vehicle_type=VehicleType.minibus,
            language="en",
            pickup_time="08:40",
        )

        reply, _, _ = build_reply(email)

        self.assertIn(
            'Please find attached a link to the pickup point you have selected. Our transport will be outside Aqua Paradise Hotel at 08:40 to collect you. You can identify our minibus by the "VIP Catamaran" sign on the front window.',
            reply,
        )

    def test_english_meet_at_catamaran_uses_official_wording(self) -> None:
        email = make_email(
            stop_name="Meet at Catamaran",
            stop_description="legacy",
            vehicle_type=VehicleType.minibus,
            language="en",
            pickup_time="08:55",
        )

        reply, _, _ = build_reply(email)

        self.assertIn(
            "Please find attached a link to the exact location of our catamaran. You must be there at 08:55 as we sail away at 08:55.",
            reply,
        )

    def test_spanish_doubledecker_stop_matches_new_structure(self) -> None:
        email = make_email(
            stop_name="Palm Court Bus Stop",
            stop_description="legacy",
            vehicle_type=VehicleType.doubledecker,
            language="es",
            pickup_time="18:30",
        )

        reply, _, _ = build_reply(email)

        self.assertIn(
            "Adjuntamos un enlace al punto de recogida que ha seleccionado.",
            reply,
        )
        self.assertIn(
            "Nuestro gran autobús rojo de dos pisos estilo Londres estará allí a las 18:30 para recogerle.",
            reply,
        )

    def test_german_minibus_stop_matches_new_structure(self) -> None:
        email = make_email(
            stop_name="SOL Nessebar Palas - with Minibus",
            stop_description="legacy",
            vehicle_type=VehicleType.minibus,
            language="de",
            pickup_time="09:40",
        )

        reply, _, _ = build_reply(email)

        self.assertIn(
            'Hier finden Sie den Link zu dem von Ihnen ausgewählten Abholpunkt.',
            reply,
        )
        self.assertIn(
            'Unser Transfer wird Sie dort um 09:40 abholen.',
            reply,
        )


if __name__ == "__main__":
    unittest.main()
