"""Database helpers.

SQLite is a good fit here because the schema is modest, the app is designed to run
locally with minimal setup, and the workload is mostly dashboard CRUD plus periodic
email polling. The models are relational, but they do not require the operational
overhead of PostgreSQL yet; switching later stays straightforward because SQLAlchemy
is used throughout and the schema avoids SQLite-specific features.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from cruise_email_dashboard.settings import settings

load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = BASE_DIR / "app.db"
DATABASE_URL = settings.database_url or f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, future=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope():
    db: Session = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    from cruise_email_dashboard.database import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _run_lightweight_migrations()


def _run_lightweight_migrations() -> None:
    """Add newly introduced nullable columns for local SQLite upgrades.

    The project started with a smaller schema. For local development we can keep the
    upgrade path friendly by adding a handful of columns in place when an older SQLite
    database already exists. This avoids asking the maintainer to manually drop tables
    whenever the app evolves during development.
    """

    if not DATABASE_URL.startswith("sqlite"):
        return

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if not existing_tables:
        return

    migrations: dict[str, dict[str, str]] = {
        "bus_stops": {
            "city_id": "INTEGER",
            "maps_url": "VARCHAR(500) NOT NULL DEFAULT ''",
            "description": "VARCHAR(500) NOT NULL DEFAULT ''",
            "vehicle_type": "VARCHAR(32) NOT NULL DEFAULT 'doubledecker'",
        },
        "hotels": {
            "city_id": "INTEGER",
        },
        "schedules": {
            "valid_days": "VARCHAR(32) NOT NULL DEFAULT ''",
        },
        "emails_log": {
            "booking_type": "VARCHAR(32) NOT NULL DEFAULT ''",
            "cruise_date": "DATE",
            "cruise_time": "TIME",
            "num_adults": "INTEGER",
            "customer_phone": "VARCHAR(64) NOT NULL DEFAULT ''",
            "booking_number": "VARCHAR(64) NOT NULL DEFAULT ''",
            "gyg_ref": "VARCHAR(64) NOT NULL DEFAULT ''",
            "total_price": "VARCHAR(64) NOT NULL DEFAULT ''",
            "raw_hotel_extraction": "VARCHAR(255) NOT NULL DEFAULT ''",
            "extraction_source": "VARCHAR(64) NOT NULL DEFAULT ''",
        },
    }

    with engine.begin() as connection:
        for table_name, columns in migrations.items():
            if table_name not in existing_tables:
                continue
            existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, column_sql in columns.items():
                if column_name not in existing_columns:
                    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}"))
