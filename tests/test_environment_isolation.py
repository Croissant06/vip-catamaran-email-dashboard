from __future__ import annotations

import unittest

from cruise_email_dashboard.database.db import DATABASE_URL


class TestEnvironmentIsolationTests(unittest.TestCase):
    def test_suite_uses_isolated_database_instead_of_app_db(self) -> None:
        self.assertNotIn("app.db", DATABASE_URL)
        self.assertIn("vip-catamaran-pytest-", DATABASE_URL)


if __name__ == "__main__":
    unittest.main()
