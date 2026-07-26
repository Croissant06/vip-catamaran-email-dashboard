from __future__ import annotations

import unittest
from datetime import date, datetime, time
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from cruise_email_dashboard.database.db import SessionLocal
from cruise_email_dashboard.database.models import BusStop, EmailLog, EmailStatus, Hotel
from cruise_email_dashboard.main import app
from tests.test_helpers import extract_csrf_token, login_with_csrf


def create_email(*, draft_reply: str) -> int:
    with SessionLocal() as db:
        hotel = db.query(Hotel).filter(Hotel.name == "CI Bootstrap Hotel").first()
        stop = db.query(BusStop).filter(BusStop.name == "Flower Street Main Bus Stop").first()
        assert hotel is not None
        assert stop is not None

        email = EmailLog(
            message_id=f"<ci-send-{uuid4().hex}@vipcatamaran.local>",
            received_at=datetime(2026, 6, 20, 11, 0, 0),
            sender_email="customer@example.com",
            sender_name="Draft Test Guest",
            subject="Morning VIP Catamaran Booking Confirmation",
            body_snippet="Draft test booking",
            full_body="Draft test booking body",
            detected_language="en",
            template_language="en",
            detected_hotel_id=hotel.id,
            assigned_bus_stop_id=stop.id,
            booking_type="MORNING",
            cruise_date=date(2026, 6, 21),
            cruise_time=time(9, 0),
            num_adults=2,
            num_children=0,
            customer_phone="+359000000001",
            booking_number=f"CI-SEND-{uuid4().hex[:8]}",
            gyg_ref=f"CIREF-{uuid4().hex[:6]}",
            total_price="120 EUR",
            detected_city="Sunny Beach",
            raw_customer_name_extraction="Draft Test Guest",
            raw_hotel_extraction=hotel.name,
            extraction_source="ci_send_test",
            pickup_time_text="08:30",
            draft_reply=draft_reply,
            status=EmailStatus.pending,
            warning_note="",
            is_new=True,
        )
        db.add(email)
        db.commit()
        db.refresh(email)
        return email.id


def create_reassign_target() -> tuple[int, int]:
    with SessionLocal() as db:
        reference_stop = db.query(BusStop).filter(BusStop.name == "Palm Court Bus Stop").first()
        assert reference_stop is not None

        hotel = Hotel(
            name=f"CI Reassign Target {uuid4().hex[:8]}",
            aliases="CI Reassign Alias",
            city_id=reference_stop.city_id,
            bus_stop_id=reference_stop.id,
        )
        db.add(hotel)
        db.commit()
        db.refresh(hotel)
        return hotel.id, reference_stop.id


class InboxSendDraftPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app, base_url="https://testserver")
        login_with_csrf(self.client, "tickets", "Vessy@02")

    def csrf_token_for_email(self, email_id: int) -> str:
        response = self.client.get(f"/inbox/{email_id}")
        self.assertEqual(response.status_code, 200)
        csrf_token = extract_csrf_token(response.text)
        self.assertIsNotNone(csrf_token)
        return csrf_token or ""

    def test_send_without_edit_uses_existing_saved_draft(self) -> None:
        email_id = create_email(draft_reply="Original stored draft")
        csrf_token = self.csrf_token_for_email(email_id)
        captured: dict[str, str] = {}

        def fake_send(email: EmailLog) -> None:
            captured["draft_reply"] = email.draft_reply or ""

        with patch("cruise_email_dashboard.routers.inbox.send_reply", side_effect=fake_send):
            response = self.client.post(
                f"/inbox/{email_id}/send",
                data={"csrf_token": csrf_token},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(captured["draft_reply"], "Original stored draft")
        with SessionLocal() as db:
            email = db.query(EmailLog).filter(EmailLog.id == email_id).first()
            self.assertIsNotNone(email)
            self.assertEqual(email.draft_reply, "Original stored draft")
            self.assertEqual(email.status, EmailStatus.sent)

    def test_send_with_submitted_edit_persists_and_sends_edited_draft(self) -> None:
        email_id = create_email(draft_reply="Original stored draft")
        csrf_token = self.csrf_token_for_email(email_id)
        captured: dict[str, str] = {}

        def fake_send(email: EmailLog) -> None:
            captured["draft_reply"] = email.draft_reply or ""

        with patch("cruise_email_dashboard.routers.inbox.send_reply", side_effect=fake_send):
            response = self.client.post(
                f"/inbox/{email_id}/send",
                data={
                    "csrf_token": csrf_token,
                    "draft_reply": "Edited draft that should be sent",
                },
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(captured["draft_reply"], "Edited draft that should be sent")
        with SessionLocal() as db:
            email = db.query(EmailLog).filter(EmailLog.id == email_id).first()
            self.assertIsNotNone(email)
            self.assertEqual(email.draft_reply, "Edited draft that should be sent")
            self.assertEqual(email.status, EmailStatus.sent)

    def test_reassign_still_updates_hotel_stop_and_manual_draft_override(self) -> None:
        email_id = create_email(draft_reply="Original stored draft")
        csrf_token = self.csrf_token_for_email(email_id)
        hotel_id, stop_id = create_reassign_target()

        response = self.client.post(
            f"/inbox/{email_id}/reassign",
            data={
                "csrf_token": csrf_token,
                "detected_hotel_id": str(hotel_id),
                "assigned_bus_stop_id": str(stop_id),
                "draft_reply": "Manual reassign draft override",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        with SessionLocal() as db:
            email = db.query(EmailLog).filter(EmailLog.id == email_id).first()
            self.assertIsNotNone(email)
            self.assertEqual(email.detected_hotel_id, hotel_id)
            self.assertEqual(email.assigned_bus_stop_id, stop_id)
            self.assertEqual(email.draft_reply, "Manual reassign draft override")
            self.assertEqual(email.status, EmailStatus.pending)


if __name__ == "__main__":
    unittest.main()
