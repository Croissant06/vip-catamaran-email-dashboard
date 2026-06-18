from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from cruise_email_dashboard.settings import Settings


class SettingsValidationTests(unittest.TestCase):
    def test_required_settings_raise_clear_error_when_missing(self) -> None:
        required_values = {
            "IMAP_PORT": "993",
            "SMTP_PORT": "587",
            "SMTP_USE_STARTTLS": "true",
            "POLL_INTERVAL_MINUTES": "5",
            "POLL_BACKOFF_MINUTES": "30",
            "MAIL_TIMEOUT_SECONDS": "10",
            "FUZZY_MATCH_THRESHOLD": "80",
            "SAFE_MODE": "true",
            "DEMO_MODE": "false",
            "DEMO_EMAIL": "",
            "DATABASE_URL": "sqlite:///test.db",
        }

        with patch.dict(os.environ, required_values, clear=True):
            with self.assertRaisesRegex(
                RuntimeError,
                "Missing required settings: IMAP_HOST, IMAP_USER, IMAP_PASSWORD, SMTP_HOST, SMTP_USER, SMTP_PASSWORD, SECRET_KEY",
            ):
                Settings()

    def test_required_settings_allow_startup_when_present(self) -> None:
        env_values = {
            "IMAP_HOST": "mail.example.com",
            "IMAP_PORT": "993",
            "IMAP_USER": "imap@example.com",
            "IMAP_PASSWORD": "imap-password",
            "SMTP_HOST": "mail.example.com",
            "SMTP_PORT": "587",
            "SMTP_USE_STARTTLS": "true",
            "SMTP_USER": "smtp@example.com",
            "SMTP_PASSWORD": "smtp-password",
            "POLL_INTERVAL_MINUTES": "5",
            "POLL_BACKOFF_MINUTES": "30",
            "MAIL_TIMEOUT_SECONDS": "10",
            "FUZZY_MATCH_THRESHOLD": "80",
            "SECRET_KEY": "super-secret-key",
            "SAFE_MODE": "true",
            "DEMO_MODE": "false",
            "DEMO_EMAIL": "",
            "DATABASE_URL": "sqlite:///test.db",
        }

        with patch.dict(os.environ, env_values, clear=True):
            settings = Settings()

        self.assertEqual(settings.imap_host, "mail.example.com")
        self.assertEqual(settings.imap_user, "imap@example.com")
        self.assertEqual(settings.smtp_host, "mail.example.com")
        self.assertEqual(settings.smtp_user, "smtp@example.com")
        self.assertEqual(settings.secret_key, "super-secret-key")


if __name__ == "__main__":
    unittest.main()
