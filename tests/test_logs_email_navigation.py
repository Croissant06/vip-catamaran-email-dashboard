from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from cruise_email_dashboard.database.db import SessionLocal
from cruise_email_dashboard.database.models import EmailLog
from cruise_email_dashboard.main import app
from tests.test_helpers import login_with_csrf


class LogsEmailNavigationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app, base_url="https://testserver")
        login_with_csrf(self.client, "tickets", "Vessy@02")

        with SessionLocal() as db:
            email = db.query(EmailLog).order_by(EmailLog.id.asc()).first()
            self.assertIsNotNone(email)
            self.email_id = email.id

    def test_logs_rows_link_to_email_detail_with_logs_return_context(self) -> None:
        response = self.client.get("/logs")

        self.assertEqual(response.status_code, 200)
        self.assertIn(f"/inbox/{self.email_id}?return_to=logs", response.text)
        self.assertIn('class="hidden text-sm text-gray-500 md:block">Live inbox monitoring</div>', response.text)
        self.assertIn('class="mb-6 flex flex-col gap-3 rounded-xl bg-white p-4 shadow md:flex-row md:items-end md:justify-between"', response.text)
        self.assertIn('class="flex min-w-0 flex-1 flex-col gap-3 md:max-w-4xl md:flex-[0_1_44rem] md:flex-row md:items-center"', response.text)
        self.assertIn('class="min-h-11 w-full shrink-0 rounded-md bg-indigo-600 px-4 py-2 text-white transition duration-150 hover:bg-indigo-700 sm:w-auto"', response.text)
        self.assertIn('class="inline-flex min-h-11 w-full shrink-0 items-center justify-center rounded-md bg-indigo-600 px-4 py-2 text-white transition duration-150 hover:bg-indigo-700 md:w-auto"', response.text)

    def test_email_detail_uses_logs_back_link_when_opened_from_logs(self) -> None:
        response = self.client.get(f"/inbox/{self.email_id}?return_to=logs")

        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/logs"', response.text)
        self.assertIn("Back to History &amp; Logs", response.text)
        self.assertIn(f'action="/inbox/{self.email_id}/send?return_to=logs"', response.text)
        self.assertIn(f'action="/inbox/{self.email_id}/reassign?return_to=logs"', response.text)


if __name__ == "__main__":
    unittest.main()
