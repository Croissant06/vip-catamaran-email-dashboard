from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from cruise_email_dashboard.database.models import BusStop, Schedule


@dataclass
class ScheduleResolution:
    schedule: Schedule | None
    warning_note: str = ""


def _season_label_for_booking(booking_type: str, cruise_date: date | None) -> str:
    booking_type = (booking_type or "").upper()
    is_september = bool(cruise_date and cruise_date.month == 9)
    if booking_type == "ANASTASIA":
        return "anastasia"
    if booking_type == "SUNSET":
        return "september_sunset" if is_september else "sunset"
    if booking_type in {"AFTERNOON", "MORNING"}:
        return "september_day" if is_september else booking_type.lower()
    if booking_type == "POMORIE":
        return "tuesday_friday_morning"
    if booking_type == "OBZOR":
        return "default"
    return "default"


def _day_matches(schedule: Schedule, cruise_date: date | None) -> bool:
    if not schedule.valid_days or not cruise_date:
        return True
    allowed_days = {part.strip() for part in schedule.valid_days.split(",") if part.strip()}
    return str(cruise_date.weekday()) in allowed_days


def resolve_pickup_schedule(
    db: Session,
    bus_stop: BusStop | None,
    booking_type: str = "",
    cruise_date: date | None = None,
) -> ScheduleResolution:
    """Resolve the correct schedule row for a booking.

    The production data now models several independent timetable families rather than a
    single generic "summer/winter" override. We first derive the exact season label from
    the booking type and cruise date, then apply two extra checks:

    1. date range matching for any limited-season rows
    2. weekday matching for restricted services like Pomorie's Tuesday/Friday pickups

    Returning a small dataclass keeps both the chosen schedule and any warning message
    together, which makes downstream email processing easier to follow.
    """

    if not bus_stop:
        return ScheduleResolution(schedule=None)

    target_date = cruise_date or date.today()
    city_name = bus_stop.city.name if bus_stop.city else ""
    target_label = _season_label_for_booking(booking_type, target_date)
    schedules = db.query(Schedule).filter(Schedule.bus_stop_id == bus_stop.id).all()

    if city_name == "Pomorie" and target_date.weekday() not in {1, 4}:
        return ScheduleResolution(
            schedule=None,
            warning_note="Pomorie pickups are Tuesday and Friday only. Please contact the customer to clarify their cruise date.",
        )

    exact_matches: list[Schedule] = []
    fallback_matches: list[Schedule] = []
    for schedule in schedules:
        start_ok = schedule.valid_from is None or schedule.valid_from <= target_date
        end_ok = schedule.valid_to is None or schedule.valid_to >= target_date
        day_ok = _day_matches(schedule, target_date)
        if not (start_ok and end_ok and day_ok):
            continue
        if schedule.season_label == target_label:
            exact_matches.append(schedule)
        elif schedule.season_label == "default":
            fallback_matches.append(schedule)

    if exact_matches:
        return ScheduleResolution(schedule=exact_matches[0])
    if fallback_matches:
        return ScheduleResolution(schedule=fallback_matches[0])
    return ScheduleResolution(schedule=None)
