from __future__ import annotations

import unittest

from cruise_email_dashboard.database.db import SessionLocal
from cruise_email_dashboard.database.models import BusStop, City, EmailLog, User


class TestSessionBootstrapTests(unittest.TestCase):
    def test_test_session_has_required_schema_and_reference_data(self) -> None:
        with SessionLocal() as db:
            self.assertIsNotNone(db.query(User).filter(User.username == "tickets").first())
            self.assertIsNotNone(db.query(User).filter(User.username == "admin").first())
            self.assertIsNotNone(db.query(City).filter(City.name == "Sunny Beach").first())
            self.assertGreaterEqual(db.query(BusStop).count(), 2)
            self.assertGreaterEqual(db.query(EmailLog).count(), 1)


if __name__ == "__main__":
    unittest.main()
