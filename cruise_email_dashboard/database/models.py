from __future__ import annotations

from datetime import date, datetime, time
from enum import Enum

from sqlalchemy import Boolean, Date, DateTime, Enum as SqlEnum, Float, ForeignKey, Integer, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cruise_email_dashboard.database.db import Base


class EmailStatus(str, Enum):
    pending = "pending"
    sent = "sent"
    flagged = "flagged"
    manual = "manual"


class UserRole(str, Enum):
    admin = "admin"
    staff = "staff"


class VehicleType(str, Enum):
    doubledecker = "doubledecker"
    minibus = "minibus"
    guide = "guide"


class City(Base):
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    local_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Sofia", nullable=False)
    aliases: Mapped[str] = mapped_column(Text, default="", nullable=False)

    hotels: Mapped[list["Hotel"]] = relationship("Hotel", back_populates="city")
    bus_stops: Mapped[list["BusStop"]] = relationship("BusStop", back_populates="city")


class BusStop(Base):
    __tablename__ = "bus_stops"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    city_id: Mapped[int | None] = mapped_column(ForeignKey("cities.id"))
    maps_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    vehicle_type: Mapped[VehicleType] = mapped_column(SqlEnum(VehicleType), default=VehicleType.doubledecker, nullable=False)

    city: Mapped["City | None"] = relationship("City", back_populates="bus_stops")
    hotels: Mapped[list["Hotel"]] = relationship("Hotel", back_populates="bus_stop")
    schedules: Mapped[list["Schedule"]] = relationship("Schedule", back_populates="bus_stop", cascade="all, delete-orphan")
    emails: Mapped[list["EmailLog"]] = relationship("EmailLog", back_populates="assigned_bus_stop")


class Hotel(Base):
    __tablename__ = "hotels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    aliases: Mapped[str] = mapped_column(Text, default="", nullable=False)
    bus_stop_id: Mapped[int | None] = mapped_column(ForeignKey("bus_stops.id"))
    city_id: Mapped[int | None] = mapped_column(ForeignKey("cities.id"))

    city: Mapped["City | None"] = relationship("City", back_populates="hotels")
    bus_stop: Mapped["BusStop | None"] = relationship("BusStop", back_populates="hotels")
    emails: Mapped[list["EmailLog"]] = relationship("EmailLog", back_populates="detected_hotel")


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bus_stop_id: Mapped[int] = mapped_column(ForeignKey("bus_stops.id"), nullable=False)
    pickup_time: Mapped[time] = mapped_column(Time, nullable=False)
    season_label: Mapped[str] = mapped_column(String(50), nullable=False, default="default")
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_days: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    bus_stop: Mapped["BusStop"] = relationship("BusStop", back_populates="schedules")


class EmailLog(Base):
    __tablename__ = "emails_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    sender_email: Mapped[str] = mapped_column(String(255), nullable=False)
    sender_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    subject: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    body_snippet: Mapped[str] = mapped_column(Text, default="", nullable=False)
    full_body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    detected_language: Mapped[str] = mapped_column(String(16), default="en", nullable=False)
    template_language: Mapped[str] = mapped_column(String(16), default="en", nullable=False)
    detected_hotel_id: Mapped[int | None] = mapped_column(ForeignKey("hotels.id"), nullable=True)
    assigned_bus_stop_id: Mapped[int | None] = mapped_column(ForeignKey("bus_stops.id"), nullable=True)
    booking_type: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    cruise_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cruise_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    num_adults: Mapped[int | None] = mapped_column(Integer, nullable=True)
    customer_phone: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    booking_number: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    gyg_ref: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    total_price: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    raw_hotel_extraction: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    extraction_source: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    pickup_time_text: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    draft_reply: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[EmailStatus] = mapped_column(SqlEnum(EmailStatus), default=EmailStatus.pending, nullable=False)
    warning_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_new: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    detected_hotel: Mapped["Hotel | None"] = relationship("Hotel", back_populates="emails")
    assigned_bus_stop: Mapped["BusStop | None"] = relationship("BusStop", back_populates="emails")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(SqlEnum(UserRole), default=UserRole.staff, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
