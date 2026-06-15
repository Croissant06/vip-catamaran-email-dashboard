from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import re
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from cruise_email_dashboard.database.db import SessionLocal, get_db
from cruise_email_dashboard.database.models import BusStop, City, EmailLog, EmailStatus, Hotel, Schedule, User, UserRole, VehicleType
from cruise_email_dashboard.dependencies import get_admin_user, get_current_user, template_context, templates
from cruise_email_dashboard.services.classifier import _build_label_map, classify_email, parse_booking_email
from cruise_email_dashboard.services.email_poller import apply_classification_to_email, poll_now, reset_poll_backoff
from cruise_email_dashboard.services.history_import import (
    get_history_import_status,
    historical_import_is_running,
    queue_historical_import,
    run_historical_import_job,
    _replace_history_import_status,
)
from cruise_email_dashboard.services.hotel_reprocess import (
    get_hotel_reprocess_status,
    hotel_reprocess_is_running,
    queue_hotel_reprocess,
    reprocess_flagged_emails,
    run_hotel_reprocess_job,
)
from cruise_email_dashboard.services.mailbox import mailbox_status
from cruise_email_dashboard.services.reply_generator import MISSING_PICKUP_TIME_PLACEHOLDER, REPLIES_DIR, available_template_files, regenerate_email_draft
from cruise_email_dashboard.services.scheduler import resolve_pickup_schedule
from cruise_email_dashboard.settings import settings, update_env

router = APIRouter(prefix="/admin", tags=["admin"])
hotel_management_router = APIRouter(tags=["hotel-management"])
DEFAULT_HISTORY_IMPORT_DATE = "2025-07-01"

DEFAULT_REPLIES_DIR = REPLIES_DIR / "defaults"
BOOKING_TYPE_CHOICES = ["", "MORNING", "AFTERNOON", "SUNSET", "ANASTASIA", "OBZOR", "POMORIE"]
LANGUAGE_CHOICES = ["en", "es", "fr", "de", "it", "el"]
TEMPLATE_PLACEHOLDERS = [
    "{customer_name}",
    "{hotel_name}",
    "{bus_stop_name}",
    "{bus_stop_address}",
    "{pickup_instructions}",
    "{pickup_time}",
    "{cruise_date}",
    "{cruise_day}",
    "{booking_type}",
    "{num_adults}",
    "{maps_url}",
    "{company_name}",
    "{company_email}",
    "{company_phone}",
    "{support_contact_info}",
]
DEMO_CITY_BOOKING_TYPES = {
    "Sunny Beach": [
        {"value": "MORNING", "label": "Morning"},
        {"value": "AFTERNOON", "label": "Afternoon"},
        {"value": "SUNSET", "label": "Sunset"},
        {"value": "ANASTASIA", "label": "Anastasia"},
    ],
    "Obzor": [
        {"value": "OBZOR", "label": "Obzor Route"},
    ],
}
PLUS_CODE_INPUT_PATTERN = re.compile(r"^[A-Z0-9]{4,8}\+[A-Z0-9]{2,3}$", re.IGNORECASE)


def _ensure_hotel_management_access(user: User) -> User:
    if user.role not in {UserRole.admin, UserRole.staff}:
        raise HTTPException(status_code=403, detail="Hotel management access required.")
    return user


def _wants_json_response(request: Request) -> bool:
    accept = request.headers.get("accept", "").lower()
    requested_with = request.headers.get("x-requested-with", "").lower()
    return "application/json" in accept or requested_with == "xmlhttprequest"


def _parse_optional_int(value: str) -> int | None:
    cleaned = str(value or "").strip()
    return int(cleaned) if cleaned else None


def _parse_optional_date(value: str):
    cleaned = str(value or "").strip()
    return datetime.strptime(cleaned, "%Y-%m-%d").date() if cleaned else None


def _parse_optional_time(value: str):
    cleaned = str(value or "").strip()
    return datetime.strptime(cleaned, "%H:%M").time() if cleaned else None


def _normalize_plus_code(value: str) -> str | None:
    cleaned = str(value or "").strip().upper().replace(" ", "")
    return cleaned or None


def _validated_plus_code(value: str) -> str | None:
    normalized = _normalize_plus_code(value)
    if normalized and not PLUS_CODE_INPUT_PATTERN.fullmatch(normalized):
        raise HTTPException(
            status_code=400,
            detail="Plus Code must look like MPW6+64 using letters/numbers, a plus sign, and 2-3 trailing characters.",
        )
    return normalized


def _normalized_return_to(return_to: str) -> str:
    return "logs" if return_to == "logs" else ""


def _detail_redirect_url(email_id: int, return_to: str) -> str:
    normalized = _normalized_return_to(return_to)
    return f"/inbox/{email_id}?return_to={normalized}" if normalized else f"/inbox/{email_id}"


def _ensure_template_defaults() -> None:
    DEFAULT_REPLIES_DIR.mkdir(parents=True, exist_ok=True)
    for path in available_template_files():
        default_path = DEFAULT_REPLIES_DIR / path.name
        if not default_path.exists():
            default_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


def _reply_template_payload() -> list[dict[str, str | bool]]:
    _ensure_template_defaults()
    payload: list[dict[str, str | bool]] = []
    for path in available_template_files():
        default_path = DEFAULT_REPLIES_DIR / path.name
        payload.append(
            {
                "name": path.name,
                "content": path.read_text(encoding="utf-8"),
                "has_default": default_path.exists(),
            }
        )
    return payload


def _city_sort_key(city: City) -> tuple[int, str]:
    order = {"Sunny Beach": 0, "Obzor": 1, "Pomorie": 2}
    return order.get(city.name, 99), city.name


def _ui_cities_with_stops(db: Session) -> list[City]:
    cities = (
        db.query(City)
        .join(BusStop, BusStop.city_id == City.id)
        .distinct()
        .order_by(City.name)
        .all()
    )
    return sorted(cities, key=_city_sort_key)


def _demo_booking_payload(db: Session) -> tuple[list[City], dict[str, list[dict[str, str | int]]], dict[str, list[dict[str, str]]]]:
    cities = _ui_cities_with_stops(db)
    hotels = db.query(Hotel).order_by(Hotel.name).all()
    city_hotels: dict[str, list[dict[str, str | int]]] = {str(city.id): [] for city in cities}
    city_booking_types: dict[str, list[dict[str, str]]] = {}

    for hotel in hotels:
        if hotel.city_id is None:
            continue
        city_hotels.setdefault(str(hotel.city_id), []).append({"id": hotel.id, "name": hotel.name})

    for city in cities:
        city_hotels[str(city.id)] = sorted(city_hotels.get(str(city.id), []), key=lambda item: str(item["name"]).lower())
        city_booking_types[str(city.id)] = DEMO_CITY_BOOKING_TYPES.get(city.name, DEMO_CITY_BOOKING_TYPES["Sunny Beach"])

    return cities, city_hotels, city_booking_types


def _next_demo_cruise_date(booking_type: str) -> date:
    candidate = datetime.now(UTC).date() + timedelta(days=1)
    if booking_type != "POMORIE":
        return candidate
    while candidate.weekday() not in {1, 4}:
        candidate += timedelta(days=1)
    return candidate


def _demo_booking_subject(booking_type: str) -> str:
    subjects = {
        "MORNING": "Morning VIP Catamaran Booking Confirmation",
        "AFTERNOON": "Afternoon VIP Catamaran Booking Confirmation",
        "SUNSET": "Sunset Cruise - VIP Catamaran Booking Confirmation",
        "ANASTASIA": "Anastasia VIP Catamaran Booking Confirmation",
        "OBZOR": "Obzor & Old Nessebar VIP Catamaran Booking Confirmation",
        "POMORIE": "Pomorie VIP Catamaran Booking Confirmation",
    }
    return subjects.get(booking_type, "VIP Catamaran Booking Confirmation")


def _create_hotel_record(db: Session, name: str, aliases: str, plus_code: str, bus_stop_id: str, city_id: str) -> Hotel:
    parsed_bus_stop_id = _parse_optional_int(bus_stop_id)
    bus_stop = db.query(BusStop).filter(BusStop.id == parsed_bus_stop_id).first() if parsed_bus_stop_id else None
    parsed_city_id = _parse_optional_int(city_id) or (bus_stop.city_id if bus_stop else None)
    hotel = Hotel(
        name=name,
        aliases=aliases,
        plus_code=_validated_plus_code(plus_code),
        bus_stop_id=parsed_bus_stop_id,
        city_id=parsed_city_id,
    )
    db.add(hotel)
    db.commit()
    return hotel


def _reprocess_flagged_emails(db: Session) -> dict[str, int]:
    summary = reprocess_flagged_emails()
    total = db.query(EmailLog).count()
    skipped_sent = db.query(EmailLog).filter(EmailLog.status == EmailStatus.sent).count()
    still_flagged = (
        db.query(EmailLog)
        .filter(EmailLog.status == EmailStatus.flagged)
        .count()
    )
    return {
        "total": total,
        "improved": summary["updated"],
        "still_flagged": still_flagged,
        "skipped_sent": skipped_sent,
    }


def _serialize_hotel(hotel: Hotel) -> dict[str, str | int | None]:
    return {
        "id": hotel.id,
        "name": hotel.name,
        "aliases": hotel.aliases or "",
        "plus_code": hotel.plus_code or "",
        "city_id": hotel.city_id,
        "city_name": hotel.city.name if hotel.city else "",
        "bus_stop_id": hotel.bus_stop_id,
        "bus_stop_name": hotel.bus_stop.name if hotel.bus_stop else "",
    }


def _hotels_for_management(db: Session) -> list[Hotel]:
    hotels = db.query(Hotel).order_by(Hotel.name.asc()).all()
    return sorted(
        hotels,
        key=lambda hotel: (
            _city_sort_key(hotel.city) if hotel.city else (99, ""),
            (hotel.name or "").lower(),
        ),
    )


def _hotel_management_payload(db: Session) -> dict[str, list[dict[str, str | int | None]]]:
    return {"hotels": [_serialize_hotel(hotel) for hotel in _hotels_for_management(db)]}


def _serialize_bus_stop(stop: BusStop) -> dict[str, str | int | None]:
    return {
        "id": stop.id,
        "name": stop.name,
        "city_id": stop.city_id,
    }


@router.get("")
def admin_page(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _ensure_hotel_management_access(user)
    return templates.TemplateResponse(
        "admin.html",
        template_context(
            request,
            user=user,
            cities=_ui_cities_with_stops(db),
            hotels=db.query(Hotel).order_by(Hotel.name).all(),
            bus_stops=db.query(BusStop).order_by(BusStop.name).all(),
            schedules=db.query(Schedule).order_by(Schedule.season_label, Schedule.pickup_time).all(),
            reply_templates=_reply_template_payload(),
            settings=settings,
            vehicle_types=list(VehicleType),
            template_placeholders=TEMPLATE_PLACEHOLDERS,
            history_import_status=get_history_import_status(),
            history_import_default_since=DEFAULT_HISTORY_IMPORT_DATE,
        ),
    )


@hotel_management_router.get("/hotel-management")
def hotel_management_page(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _ensure_hotel_management_access(user)
    return templates.TemplateResponse(
        "hotel_management.html",
        template_context(
            request,
            user=user,
            cities=_ui_cities_with_stops(db),
            bus_stops=db.query(BusStop).order_by(BusStop.name).all(),
            bus_stops_payload=[_serialize_bus_stop(stop) for stop in db.query(BusStop).order_by(BusStop.name).all()],
            hotels=_hotels_for_management(db),
            hotels_payload=_hotel_management_payload(db)["hotels"],
            hotel_reprocess_status=get_hotel_reprocess_status(),
        ),
    )


@hotel_management_router.post("/hotel-management/reprocess-flagged")
def hotel_management_reprocess_flagged(request: Request, user: User = Depends(get_current_user)):
    _ensure_hotel_management_access(user)
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler is not available.")

    if hotel_reprocess_is_running():
        payload = get_hotel_reprocess_status()
        status_code = 409
    else:
        payload = queue_hotel_reprocess()
        try:
            scheduler.add_job(
                run_hotel_reprocess_job,
                "date",
                run_date=datetime.now(UTC),
                id="hotel_management_reprocess",
                replace_existing=False,
                max_instances=1,
            )
            payload = get_hotel_reprocess_status()
            status_code = 202
        except Exception as exc:
            payload = {
                **get_hotel_reprocess_status(),
                "status": "failed",
                "finished_at": datetime.now(UTC).isoformat(),
                "message": f"Reprocessing failed to start - {exc}",
            }
            status_code = 500

    if _wants_json_response(request):
        return JSONResponse(payload, status_code=status_code)
    return RedirectResponse(url="/hotel-management", status_code=303)


@hotel_management_router.get("/hotel-management/reprocess-flagged-status")
def hotel_management_reprocess_flagged_status(user: User = Depends(get_current_user)):
    _ensure_hotel_management_access(user)
    return JSONResponse(get_hotel_reprocess_status())


@hotel_management_router.get("/hotel-management/hotels")
def hotel_management_hotels(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _ensure_hotel_management_access(user)
    return JSONResponse(_hotel_management_payload(db))


@router.get("/create-demo-booking")
def admin_demo_booking_page(request: Request, db: Session = Depends(get_db), user: User = Depends(get_admin_user)):
    cities, city_hotels, city_booking_types = _demo_booking_payload(db)
    default_city_id = cities[0].id if cities else None
    return templates.TemplateResponse(
        "demo_booking.html",
        template_context(
            request,
            user=user,
            cities=cities,
            city_hotels=city_hotels,
            city_booking_types=city_booking_types,
            default_city_id=default_city_id,
        ),
    )


@router.post("/create-demo-booking")
def admin_create_demo_booking(
    customer_name: str = Form("Demo Guest"),
    sender_email: str = Form("pressiyan@gmail.com"),
    city_id: int = Form(...),
    hotel_id: int = Form(...),
    booking_type: str = Form(...),
    num_adults: int = Form(2),
    num_children: int = Form(0),
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    city = db.query(City).filter(City.id == city_id).first()
    hotel = db.query(Hotel).filter(Hotel.id == hotel_id).first()
    if not city or not hotel or hotel.city_id != city.id:
        raise HTTPException(status_code=400, detail="Selected city or hotel is invalid.")
    if hotel.bus_stop is None:
        raise HTTPException(status_code=400, detail="Selected hotel does not have an assigned bus stop.")

    allowed_booking_types = {item["value"] for item in DEMO_CITY_BOOKING_TYPES.get(city.name, [])}
    if booking_type not in allowed_booking_types:
        raise HTTPException(status_code=400, detail="Selected booking type is not valid for that city.")

    cruise_date = _next_demo_cruise_date(booking_type)
    received_at = datetime.now(UTC).replace(tzinfo=None)
    booking_number = f"DEMO-{received_at:%Y%m%d%H%M%S}"
    email_log = EmailLog(
        message_id=f"<demo-{uuid4()}@vipcatamaran.local>",
        received_at=received_at,
        sender_email=sender_email.strip(),
        sender_name=customer_name.strip() or "Demo Guest",
        subject=_demo_booking_subject(booking_type),
        body_snippet=f"Demo booking for {hotel.name} ({city.name})",
        full_body=f"Demo booking generated from admin panel for {hotel.name}, {city.name}.",
        html_body=None,
        detected_language="en",
        template_language="en",
        booking_type=booking_type,
        cruise_date=cruise_date,
        num_adults=max(num_adults, 1),
        num_children=max(num_children, 0),
        booking_number=booking_number,
        gyg_ref=f"DEMO{received_at:%H%M%S}",
        total_price="",
        detected_city=city.name,
        raw_customer_name_extraction=customer_name.strip() or "Demo Guest",
        raw_hotel_extraction=hotel.name,
        extraction_source="demo_booking",
        status=EmailStatus.pending,
        warning_note="",
        is_new=True,
    )
    email_log.detected_hotel = hotel
    email_log.assigned_bus_stop = hotel.bus_stop
    db.add(email_log)
    db.flush()

    schedule_resolution = resolve_pickup_schedule(db, hotel.bus_stop, booking_type, cruise_date)
    email_log.pickup_time_text = (
        schedule_resolution.schedule.pickup_time.strftime("%H:%M")
        if schedule_resolution.schedule
        else MISSING_PICKUP_TIME_PLACEHOLDER
    )
    email_log.warning_note = schedule_resolution.warning_note or ""
    regenerate_email_draft(email_log)
    email_log.status = EmailStatus.pending
    db.commit()
    return RedirectResponse(url=f"/inbox?highlight={email_log.id}", status_code=303)


@router.get("/mailbox-status")
def admin_mailbox_status(user: User = Depends(get_admin_user)):
    return JSONResponse(mailbox_status())


@router.get("/debug-parse/{email_log_id}")
def admin_debug_parse(email_log_id: int, db: Session = Depends(get_db), user: User = Depends(get_admin_user)):
    email = db.query(EmailLog).filter(EmailLog.id == email_log_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found.")

    html_body = email.html_body or ""
    text_body = email.full_body or ""
    parsed = parse_booking_email(
        subject=email.subject or "",
        text_body=text_body,
        html_body=html_body,
        fallback_sender=email.sender_email or "",
        fallback_name=email.sender_name or "",
    )
    classified = classify_email(
        db,
        subject=email.subject or "",
        body=text_body,
        threshold=settings.fuzzy_match_threshold,
        html_body=html_body,
        fallback_sender=email.sender_email or "",
        fallback_name=email.sender_name or "",
    )
    resolved_bus_stop = classified.matched_bus_stop or (classified.matched_hotel.bus_stop if classified.matched_hotel else None)
    label_map = _build_label_map(html_body, text_body)
    return JSONResponse(
        {
            "notes_block": parsed.notes_block,
            "label_map_keys": list(label_map.keys()),
            "html_body_length": len(html_body) if html_body else 0,
            "raw_hotel_extraction": parsed.raw_hotel_extraction,
            "raw_customer_name_extraction": parsed.raw_customer_name_extraction,
            "extraction_source": classified.extraction_source,
            "parsed_extraction_source": parsed.extraction_source,
            "booking_type": parsed.booking_type,
            "detected_city": parsed.city_name,
            "matched_hotel_name": classified.matched_hotel.name if classified.matched_hotel else None,
            "matched_bus_stop_name": resolved_bus_stop.name if resolved_bus_stop else None,
            "selected_stop_time_text": classified.selected_stop_time_text,
            "num_adults": classified.num_adults,
            "num_children": classified.num_children,
            "stored_num_adults": email.num_adults,
            "stored_num_children": email.num_children,
            "classified_extraction_source": classified.extraction_source,
            "classified_warning_note": classified.warning_note,
        }
    )


@router.post("/mailbox-status/reset-backoff")
async def admin_reset_backoff(user: User = Depends(get_admin_user)):
    reset_poll_backoff()
    result = await poll_now(SessionLocal, force=True)
    status = mailbox_status()
    return JSONResponse({"poll_result": result, **status})


@router.post("/mailbox-status/run-poll")
async def admin_run_poll_now(user: User = Depends(get_admin_user)):
    return JSONResponse(await poll_now(SessionLocal, force=False))


@router.post("/mailbox-status/import-history")
def admin_import_history(
    request: Request,
    since_date: str = Form(DEFAULT_HISTORY_IMPORT_DATE),
    user: User = Depends(get_admin_user),
):
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler is not available.")

    if historical_import_is_running():
        status_payload = get_history_import_status()
        status_code = 409
    else:
        queue_historical_import(since_date=since_date)
        try:
            scheduler.add_job(
                run_historical_import_job,
                "date",
                run_date=datetime.now(UTC),
                kwargs={"since_date": since_date},
                id="historical_import",
                replace_existing=False,
                max_instances=1,
            )
            status_payload = get_history_import_status()
            status_code = 202
        except Exception as exc:
            status_payload = _replace_history_import_status(
                {
                    **get_history_import_status(),
                    "status": "failed",
                    "finished_at": datetime.now(UTC).isoformat(),
                    "message": f"Import failed to start - {exc}",
                }
            )
            status_code = 500

    if _wants_json_response(request):
        return JSONResponse(status_payload, status_code=status_code)
    return RedirectResponse(url="/admin", status_code=303)


@router.get("/mailbox-status/import-history-status")
def admin_import_history_status(user: User = Depends(get_admin_user)):
    return JSONResponse(get_history_import_status())


@router.post("/reprocess-all")
def admin_reprocess_all(db: Session = Depends(get_db), user: User = Depends(get_admin_user)):
    return JSONResponse(_reprocess_flagged_emails(db))


@router.post("/hotels")
def create_hotel(
    name: str = Form(...),
    aliases: str = Form(""),
    plus_code: str = Form(""),
    bus_stop_id: str = Form(""),
    city_id: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ensure_hotel_management_access(user)
    _create_hotel_record(db, name=name, aliases=aliases, plus_code=plus_code, bus_stop_id=bus_stop_id, city_id=city_id)
    return RedirectResponse(url="/admin", status_code=303)


@hotel_management_router.post("/hotel-management/hotels")
def create_hotel_from_hotel_management(
    request: Request,
    name: str = Form(...),
    aliases: str = Form(""),
    plus_code: str = Form(""),
    bus_stop_id: str = Form(""),
    city_id: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ensure_hotel_management_access(user)
    hotel = _create_hotel_record(db, name=name, aliases=aliases, plus_code=plus_code, bus_stop_id=bus_stop_id, city_id=city_id)
    db.refresh(hotel)
    if _wants_json_response(request):
        return JSONResponse({"ok": True, "hotel": _serialize_hotel(hotel), **_hotel_management_payload(db)})
    return RedirectResponse(url="/hotel-management", status_code=303)


@hotel_management_router.post("/hotel-management/hotels/{hotel_id}/bus-stop")
def update_hotel_bus_stop_from_hotel_management(
    request: Request,
    hotel_id: int,
    bus_stop_id: str = Form(""),
    plus_code: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ensure_hotel_management_access(user)
    hotel = db.query(Hotel).filter(Hotel.id == hotel_id).first()
    if hotel is None:
        raise HTTPException(status_code=404, detail="Hotel not found.")

    parsed_bus_stop_id = _parse_optional_int(bus_stop_id)
    bus_stop = db.query(BusStop).filter(BusStop.id == parsed_bus_stop_id).first() if parsed_bus_stop_id else None
    hotel.bus_stop_id = parsed_bus_stop_id
    hotel.plus_code = _validated_plus_code(plus_code)
    if bus_stop is not None:
        hotel.city_id = bus_stop.city_id
    db.commit()
    db.refresh(hotel)
    if _wants_json_response(request):
        return JSONResponse({"ok": True, "hotel": _serialize_hotel(hotel), **_hotel_management_payload(db)})
    return RedirectResponse(url="/hotel-management", status_code=303)


@hotel_management_router.post("/hotel-management/hotels/{hotel_id}/delete")
def delete_hotel_from_hotel_management(
    request: Request,
    hotel_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ensure_hotel_management_access(user)
    hotel = db.query(Hotel).filter(Hotel.id == hotel_id).first()
    if hotel is not None:
        db.delete(hotel)
        db.commit()
    if _wants_json_response(request):
        return JSONResponse({"ok": True, **_hotel_management_payload(db)})
    return RedirectResponse(url="/hotel-management", status_code=303)


@router.post("/hotels/{hotel_id}")
def update_hotel(
    hotel_id: int,
    name: str = Form(...),
    aliases: str = Form(""),
    plus_code: str = Form(""),
    bus_stop_id: str = Form(""),
    city_id: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    hotel = db.query(Hotel).filter(Hotel.id == hotel_id).first()
    parsed_bus_stop_id = _parse_optional_int(bus_stop_id)
    bus_stop = db.query(BusStop).filter(BusStop.id == parsed_bus_stop_id).first() if parsed_bus_stop_id else None
    hotel.name = name
    hotel.aliases = aliases
    hotel.plus_code = _validated_plus_code(plus_code)
    hotel.bus_stop_id = parsed_bus_stop_id
    hotel.city_id = _parse_optional_int(city_id) or (bus_stop.city_id if bus_stop else None)
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/hotels/{hotel_id}/delete")
def delete_hotel(hotel_id: int, db: Session = Depends(get_db), user: User = Depends(get_admin_user)):
    hotel = db.query(Hotel).filter(Hotel.id == hotel_id).first()
    if hotel:
        db.delete(hotel)
        db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/bus-stops")
def create_stop(
    name: str = Form(...),
    address: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    city_id: str = Form(""),
    maps_url: str = Form(""),
    description: str = Form(""),
    vehicle_type: VehicleType = Form(VehicleType.doubledecker),
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    db.add(
        BusStop(
            name=name,
            address=address,
            latitude=latitude,
            longitude=longitude,
            city_id=_parse_optional_int(city_id),
            maps_url=maps_url,
            description=description,
            vehicle_type=vehicle_type,
        )
    )
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/bus-stops/{stop_id}")
def update_stop(
    stop_id: int,
    name: str = Form(...),
    address: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    city_id: str = Form(""),
    maps_url: str = Form(""),
    description: str = Form(""),
    vehicle_type: VehicleType = Form(VehicleType.doubledecker),
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    stop = db.query(BusStop).filter(BusStop.id == stop_id).first()
    stop.name = name
    stop.address = address
    stop.latitude = latitude
    stop.longitude = longitude
    stop.city_id = _parse_optional_int(city_id)
    stop.maps_url = maps_url
    stop.description = description
    stop.vehicle_type = vehicle_type
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/bus-stops/{stop_id}/delete")
def delete_stop(stop_id: int, db: Session = Depends(get_db), user: User = Depends(get_admin_user)):
    stop = db.query(BusStop).filter(BusStop.id == stop_id).first()
    if stop:
        db.delete(stop)
        db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/schedules")
def create_schedule(
    bus_stop_id: int = Form(...),
    pickup_time: str = Form(...),
    season_label: str = Form(...),
    valid_from: str = Form(""),
    valid_to: str = Form(""),
    valid_days: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    parsed_pickup_time = datetime.strptime(pickup_time, "%H:%M").time()
    db.add(
        Schedule(
            bus_stop_id=bus_stop_id,
            pickup_time=parsed_pickup_time,
            season_label=season_label,
            valid_from=_parse_optional_date(valid_from),
            valid_to=_parse_optional_date(valid_to),
            valid_days=valid_days,
        )
    )
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/schedules/{schedule_id}")
def update_schedule(
    schedule_id: int,
    bus_stop_id: int = Form(...),
    pickup_time: str = Form(...),
    season_label: str = Form(...),
    valid_from: str = Form(""),
    valid_to: str = Form(""),
    valid_days: str = Form(""),
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    schedule.bus_stop_id = bus_stop_id
    schedule.pickup_time = datetime.strptime(pickup_time, "%H:%M").time()
    schedule.season_label = season_label
    schedule.valid_from = _parse_optional_date(valid_from)
    schedule.valid_to = _parse_optional_date(valid_to)
    schedule.valid_days = valid_days
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/schedules/{schedule_id}/delete")
def delete_schedule(schedule_id: int, db: Session = Depends(get_db), user: User = Depends(get_admin_user)):
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if schedule:
        db.delete(schedule)
        db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/templates/{template_name}")
async def save_template(template_name: str, request: Request, user: User = Depends(get_admin_user)):
    _ensure_template_defaults()
    form = await request.form()
    content = form.get("content", "")
    path = REPLIES_DIR / template_name
    path.write_text(str(content), encoding="utf-8")
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/templates/{template_name}/reset")
def reset_template(template_name: str, user: User = Depends(get_admin_user)):
    _ensure_template_defaults()
    default_path = DEFAULT_REPLIES_DIR / template_name
    target_path = REPLIES_DIR / template_name
    if not default_path.exists():
        raise HTTPException(status_code=404, detail="Default template backup not found.")
    target_path.write_text(default_path.read_text(encoding="utf-8"), encoding="utf-8")
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/emails/{email_id}/parser")
def update_email_parser_fields(
    email_id: int,
    return_to: str = Query(default=""),
    booking_type: str = Form(""),
    cruise_date: str = Form(""),
    cruise_time: str = Form(""),
    detected_language: str = Form("en"),
    raw_hotel_extraction: str = Form(""),
    extraction_source: str = Form(""),
    customer_phone: str = Form(""),
    booking_number: str = Form(""),
    gyg_ref: str = Form(""),
    total_price: str = Form(""),
    num_adults: str = Form(""),
    num_children: str = Form(""),
    warning_note: str = Form(""),
    regenerate_draft: str = Form("true"),
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    email = db.query(EmailLog).filter(EmailLog.id == email_id).first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found.")

    email.booking_type = booking_type.strip().upper()
    email.cruise_date = _parse_optional_date(cruise_date)
    email.cruise_time = _parse_optional_time(cruise_time)
    email.detected_language = (detected_language or "en").strip().lower()
    email.raw_hotel_extraction = raw_hotel_extraction.strip()
    email.extraction_source = extraction_source.strip() or ("manual_override" if email.raw_hotel_extraction else "")
    email.customer_phone = customer_phone.strip()
    email.booking_number = booking_number.strip()
    email.gyg_ref = gyg_ref.strip().upper()
    email.total_price = total_price.strip()
    email.num_adults = int(num_adults.strip()) if num_adults.strip() else None
    email.num_children = int(num_children.strip()) if num_children.strip() else None

    warning_parts = [warning_note.strip()] if warning_note.strip() else []
    schedule_resolution = resolve_pickup_schedule(db, email.assigned_bus_stop, email.booking_type, email.cruise_date)
    email.pickup_time_text = (
        schedule_resolution.schedule.pickup_time.strftime("%H:%M")
        if schedule_resolution.schedule
        else MISSING_PICKUP_TIME_PLACEHOLDER
    )
    if schedule_resolution.warning_note:
        warning_parts.append(schedule_resolution.warning_note)
    email.warning_note = "\n".join(part for part in warning_parts if part).strip()
    if schedule_resolution.warning_note and "Pomorie operates Tuesday and Friday only" in schedule_resolution.warning_note:
        email.status = EmailStatus.flagged
    elif email.assigned_bus_stop:
        email.status = EmailStatus.pending

    if regenerate_draft == "true" and email.assigned_bus_stop:
        regenerate_email_draft(email)
        if email.warning_note and schedule_resolution.warning_note and schedule_resolution.warning_note not in email.warning_note:
            email.warning_note = "\n".join(part for part in [email.warning_note, schedule_resolution.warning_note] if part).strip()
    elif not email.assigned_bus_stop:
        email.template_language = email.detected_language or "en"

    db.commit()
    return RedirectResponse(url=_detail_redirect_url(email_id, return_to), status_code=303)


@router.post("/settings")
def save_settings(
    imap_host: str = Form(""),
    imap_port: int = Form(...),
    imap_user: str = Form(""),
    imap_password: str = Form(""),
    smtp_host: str = Form(""),
    smtp_port: int = Form(...),
    smtp_user: str = Form(""),
    smtp_password: str = Form(""),
    poll_interval_minutes: int = Form(...),
    poll_backoff_minutes: int = Form(...),
    mail_timeout_seconds: int = Form(...),
    fuzzy_match_threshold: int = Form(...),
    secret_key: str = Form(...),
    safe_mode: str = Form("true"),
    demo_mode: str = Form("false"),
    user: User = Depends(get_admin_user),
):
    update_env(
        {
            "IMAP_HOST": imap_host,
            "IMAP_PORT": str(imap_port),
            "IMAP_USER": imap_user,
            "IMAP_PASSWORD": imap_password,
            "SMTP_HOST": smtp_host,
            "SMTP_PORT": str(smtp_port),
            "SMTP_USER": smtp_user,
            "SMTP_PASSWORD": smtp_password,
            "POLL_INTERVAL_MINUTES": str(poll_interval_minutes),
            "POLL_BACKOFF_MINUTES": str(poll_backoff_minutes),
            "MAIL_TIMEOUT_SECONDS": str(mail_timeout_seconds),
            "FUZZY_MATCH_THRESHOLD": str(fuzzy_match_threshold),
            "SECRET_KEY": secret_key,
            "SAFE_MODE": safe_mode,
            "DEMO_MODE": demo_mode,
        }
    )
    return RedirectResponse(url="/admin", status_code=303)
