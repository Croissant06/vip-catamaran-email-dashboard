from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from cruise_email_dashboard.database.db import SessionLocal
from cruise_email_dashboard.database.models import EmailLog
from cruise_email_dashboard.main import app


class LogsEmailNavigationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        response = self.client.post(
            "/login",
            data={"username": "tickets", "password": "Vessy@02"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        with SessionLocal() as db:
            email = db.query(EmailLog).order_by(EmailLog.id.asc()).first()
            self.assertIsNotNone(email)
            self.email_id = email.id

    def test_logs_rows_link_to_email_detail_with_logs_return_context(self) -> None:
        response = self.client.get("/logs")

        self.assertEqual(response.status_code, 200)
        self.assertIn(f"/inbox/{self.email_id}?return_to=logs", response.text)

    def test_email_detail_uses_logs_back_link_when_opened_from_logs(self) -> None:
        response = self.client.get(f"/inbox/{self.email_id}?return_to=logs")

        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/logs"', response.text)
        self.assertIn("Back to History &amp; Logs", response.text)
        self.assertIn(f'action="/inbox/{self.email_id}/send?return_to=logs"', response.text)
        self.assertIn(f'action="/inbox/{self.email_id}/reassign?return_to=logs"', response.text)


if __name__ == "__main__":
    unittest.main()
