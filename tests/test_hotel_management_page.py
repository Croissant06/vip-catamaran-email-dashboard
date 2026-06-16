from __future__ import annotations

import unittest
from unittest.mock import patch
from types import SimpleNamespace

from fastapi.testclient import TestClient

from cruise_email_dashboard.database.db import SessionLocal
from cruise_email_dashboard.database.models import BusStop, City, Hotel
from cruise_email_dashboard.main import app


class HotelManagementPageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.app.state.scheduler = SimpleNamespace(add_job=lambda *args, **kwargs: None)
        response = self.client.post(
            "/login",
            data={"username": "tickets", "password": "Vessy@02"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

    def tearDown(self) -> None:
        with SessionLocal() as db:
            for hotel in db.query(Hotel).filter(Hotel.name.like("Codex HM Test %")).all():
                db.delete(hotel)
            db.commit()

    def test_staff_hotel_table_endpoints_create_update_delete_without_reload(self) -> None:
        with SessionLocal() as db:
            city = db.query(City).filter(City.name == "Sunny Beach").first()
            self.assertIsNotNone(city)
            city_id = city.id
            stops = (
                db.query(BusStop)
                .filter(BusStop.city_id == city.id)
                .order_by(BusStop.name.asc())
                .all()
            )
            self.assertGreaterEqual(len(stops), 2)
            stop_id = stops[0].id
            replacement_stop_id = stops[-1].id

        create_response = self.client.post(
            "/hotel-management/hotels",
            headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            data={
                "name": "Codex HM Test Create",
                "aliases": "Codex Alias",
                "plus_code": "MPW6+64",
                "city_id": str(city_id),
                "bus_stop_id": str(stop_id),
            },
        )
        self.assertEqual(create_response.status_code, 200)
        created_payload = create_response.json()
        self.assertEqual(created_payload["hotel"]["name"], "Codex HM Test Create")
        self.assertEqual(created_payload["hotel"]["plus_code"], "MPW6+64")
        hotel_id = created_payload["hotel"]["id"]

        list_response = self.client.get(
            "/hotel-management/hotels",
            headers={"Accept": "application/json"},
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertTrue(any(row["id"] == hotel_id for row in list_response.json()["hotels"]))

        update_response = self.client.post(
            f"/hotel-management/hotels/{hotel_id}/bus-stop",
            headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            data={"bus_stop_id": str(replacement_stop_id), "plus_code": "QQ22+AB"},
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["hotel"]["bus_stop_id"], replacement_stop_id)
        self.assertEqual(update_response.json()["hotel"]["plus_code"], "QQ22+AB")

        delete_response = self.client.post(
            f"/hotel-management/hotels/{hotel_id}/delete",
            headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertTrue(delete_response.json()["ok"])

    def test_reprocess_start_returns_immediately_and_exposes_status_endpoint(self) -> None:
        fake_status = {
            "status": "queued",
            "started_at": "2026-06-08T12:00:00+00:00",
            "finished_at": None,
            "total_selected": 5,
            "processed": 0,
            "updated": 0,
            "failed": 0,
            "message": "Reprocessing started...",
        }

        with patch("cruise_email_dashboard.routers.admin.queue_hotel_reprocess", return_value=fake_status), patch(
            "cruise_email_dashboard.routers.admin.get_hotel_reprocess_status",
            return_value=fake_status,
        ), patch.object(self.client.app.state.scheduler, "add_job", return_value=None):
            start_response = self.client.post(
                "/hotel-management/reprocess-flagged",
                headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            )

        self.assertEqual(start_response.status_code, 202)
        self.assertEqual(start_response.json()["status"], "queued")

        with patch("cruise_email_dashboard.routers.admin.get_hotel_reprocess_status", return_value=fake_status):
            status_response = self.client.get(
                "/hotel-management/reprocess-flagged-status",
                headers={"Accept": "application/json"},
            )

        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.json()["message"], "Reprocessing started...")

    def test_admin_page_shows_plus_code_field(self) -> None:
        admin_client = TestClient(app)
        admin_client.app.state.scheduler = SimpleNamespace(add_job=lambda *args, **kwargs: None)
        response = admin_client.post(
            "/login",
            data={"username": "admin", "password": "admin123"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        admin_page = admin_client.get("/admin")

        self.assertEqual(admin_page.status_code, 200)
        self.assertIn('name="plus_code"', admin_page.text)

    def test_staff_hotel_create_rejects_invalid_plus_code(self) -> None:
        with SessionLocal() as db:
            city = db.query(City).filter(City.name == "Sunny Beach").first()
            self.assertIsNotNone(city)
            stop = (
                db.query(BusStop)
                .filter(BusStop.city_id == city.id)
                .order_by(BusStop.name.asc())
                .first()
            )
            self.assertIsNotNone(stop)

        response = self.client.post(
            "/hotel-management/hotels",
            headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            data={
                "name": "Codex HM Test Invalid Plus",
                "aliases": "",
                "plus_code": "not-a-plus-code",
                "city_id": str(city.id),
                "bus_stop_id": str(stop.id),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Plus Code", response.json()["detail"])

    def test_staff_hotel_create_rejects_duplicate_name_case_insensitive(self) -> None:
        with SessionLocal() as db:
            city = db.query(City).filter(City.name == "Sunny Beach").first()
            self.assertIsNotNone(city)
            stop = (
                db.query(BusStop)
                .filter(BusStop.city_id == city.id)
                .order_by(BusStop.name.asc())
                .first()
            )
            self.assertIsNotNone(stop)
            db.add(
                Hotel(
                    name="Codex HM Test Existing",
                    aliases="Existing Alias",
                    bus_stop_id=stop.id,
                    city_id=city.id,
                )
            )
            db.commit()

        response = self.client.post(
            "/hotel-management/hotels",
            headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
            data={
                "name": "codex hm test existing",
                "aliases": "",
                "plus_code": "",
                "city_id": str(city.id),
                "bus_stop_id": str(stop.id),
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("already exists", response.json()["detail"])
        self.assertIn("Codex HM Test Existing", response.json()["detail"])

    def test_home_page_does_not_show_average_response_time(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Average response time", response.text)


if __name__ == "__main__":
    unittest.main()
