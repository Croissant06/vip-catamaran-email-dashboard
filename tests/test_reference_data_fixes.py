from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import cruise_email_dashboard.database.db as db_module
from cruise_email_dashboard.database.models import Base, BusStop, City, Hotel


class ReferenceDataFixesTests(unittest.TestCase):
    def test_existing_hotels_keep_staff_managed_fields_while_missing_hotels_are_created(self) -> None:
        original_engine = db_module.engine
        original_session_local = db_module.SessionLocal
        original_database_url = db_module.DATABASE_URL

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db_path = Path(tmpdir) / "reference-data-test.db"
            temp_engine = create_engine(f"sqlite:///{temp_db_path.as_posix()}", future=True, connect_args={"check_same_thread": False})
            temp_session_local = sessionmaker(
                bind=temp_engine,
                autoflush=False,
                autocommit=False,
                expire_on_commit=False,
            )
            db_module.engine = temp_engine
            db_module.SessionLocal = temp_session_local
            db_module.DATABASE_URL = f"sqlite:///{temp_db_path.as_posix()}"

            try:
                Base.metadata.create_all(bind=temp_engine)

                with db_module.session_scope() as db:
                    sunny_beach = City(name="Sunny Beach", local_name="Sunny Beach", timezone="Europe/Sofia", aliases="")
                    db.add(sunny_beach)
                    db.flush()

                    persani_stop = BusStop(
                        name="Persani (Black Sea Hotel Bus Stop)",
                        address="Persani",
                        latitude=42.0,
                        longitude=27.0,
                        city_id=sunny_beach.id,
                        maps_url="https://example.com/persani",
                        description="Persani stop",
                    )
                    royal_sun_stop = BusStop(
                        name="Royal Sun / Arda Bus Stop",
                        address="Royal Sun",
                        latitude=42.1,
                        longitude=27.1,
                        city_id=sunny_beach.id,
                        maps_url="https://example.com/royal-sun",
                        description="Royal Sun stop",
                    )
                    flower_street_stop = BusStop(
                        name="Flower Street Main Bus Stop",
                        address="Flower Street",
                        latitude=42.2,
                        longitude=27.2,
                        city_id=sunny_beach.id,
                        maps_url="https://example.com/flower",
                        description="Flower stop",
                    )
                    mercury_stop = BusStop(
                        name="Mercury Grand Market",
                        address="Mercury",
                        latitude=42.3,
                        longitude=27.3,
                        city_id=sunny_beach.id,
                        maps_url="https://example.com/mercury",
                        description="Mercury stop",
                    )
                    best_western_stop = BusStop(
                        name="Hotel Best Western / Sveshest",
                        address="Best Western",
                        latitude=42.4,
                        longitude=27.4,
                        city_id=sunny_beach.id,
                        maps_url="https://example.com/best-western",
                        description="Best Western stop",
                    )
                    db.add_all([persani_stop, royal_sun_stop, flower_street_stop, mercury_stop, best_western_stop])
                    db.flush()

                    db.add(
                        Hotel(
                            name="Royal Sun / Arda",
                            aliases="Custom Royal Sun Alias",
                            bus_stop_id=royal_sun_stop.id,
                            city_id=sunny_beach.id,
                        )
                    )

                db_module._run_reference_data_fixes()

                with db_module.session_scope() as db:
                    existing_hotel = db.query(Hotel).filter(Hotel.name == "Royal Sun / Arda").first()
                    self.assertIsNotNone(existing_hotel)
                    self.assertEqual(existing_hotel.aliases, "Custom Royal Sun Alias")
                    self.assertEqual(existing_hotel.bus_stop_id, royal_sun_stop.id)
                    self.assertEqual(existing_hotel.city_id, sunny_beach.id)

                    created_hotel = db.query(Hotel).filter(Hotel.name == "Favorit Aparthotel").first()
                    self.assertIsNotNone(created_hotel)
                    self.assertEqual(created_hotel.bus_stop_id, flower_street_stop.id)
                    self.assertEqual(created_hotel.city_id, sunny_beach.id)
                    self.assertEqual(created_hotel.aliases, "Favorit,Favorit Apart")
            finally:
                temp_engine.dispose()
                db_module.engine = original_engine
                db_module.SessionLocal = original_session_local
                db_module.DATABASE_URL = original_database_url


if __name__ == "__main__":
    unittest.main()
