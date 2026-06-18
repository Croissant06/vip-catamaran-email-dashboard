from __future__ import annotations

import re
import unittest

from fastapi.testclient import TestClient

from cruise_email_dashboard.database.db import SessionLocal
from cruise_email_dashboard.database.models import EmailLog
from cruise_email_dashboard.main import app


def extract_csrf_token(html: str) -> str | None:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    if match:
        return match.group(1)
    meta_match = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
    if meta_match:
        return meta_match.group(1)
    return None


class CsrfProtectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app, base_url="https://testserver")

    def login_with_csrf(self, username: str = "tickets", password: str = "Vessy@02") -> None:
        login_page = self.client.get("/login")
        self.assertEqual(login_page.status_code, 200)
        csrf_token = extract_csrf_token(login_page.text)
        self.assertIsNotNone(csrf_token)

        response = self.client.post(
            "/login",
            data={"username": username, "password": password, "csrf_token": csrf_token},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

    def test_login_rejects_missing_csrf_token(self) -> None:
        response = self.client.post(
            "/login",
            data={"username": "tickets", "password": "Vessy@02"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("CSRF", response.text)

    def test_login_accepts_valid_csrf_token(self) -> None:
        login_page = self.client.get("/login")

        self.assertEqual(login_page.status_code, 200)
        csrf_token = extract_csrf_token(login_page.text)
        self.assertIsNotNone(csrf_token)

        response = self.client.post(
            "/login",
            data={"username": "tickets", "password": "Vessy@02", "csrf_token": csrf_token},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/")

    def test_ajax_post_rejects_missing_csrf_header_and_accepts_valid_header(self) -> None:
        self.login_with_csrf()
        inbox_page = self.client.get("/inbox")
        csrf_token = extract_csrf_token(inbox_page.text)
        self.assertIsNotNone(csrf_token)

        with SessionLocal() as db:
            email = db.query(EmailLog).order_by(EmailLog.id.asc()).first()
            self.assertIsNotNone(email)
            email_id = email.id

        rejected = self.client.post(
            f"/inbox/{email_id}/mark-unread",
            headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(rejected.status_code, 403)
        self.assertIn("CSRF", rejected.text)

        accepted = self.client.post(
            f"/inbox/{email_id}/mark-unread",
            headers={
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRF-Token": csrf_token,
            },
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertTrue(accepted.json()["ok"])


if __name__ == "__main__":
    unittest.main()
