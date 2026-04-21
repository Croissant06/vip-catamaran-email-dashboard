from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from cruise_email_dashboard.database.db import get_db
from cruise_email_dashboard.database.models import BusStop, Hotel, Schedule, User
from cruise_email_dashboard.dependencies import get_admin_user, template_context, templates
from cruise_email_dashboard.services.mailbox import mailbox_status
from cruise_email_dashboard.services.reply_generator import REPLIES_DIR, available_template_files
from cruise_email_dashboard.settings import settings, update_env

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("")
def admin_page(request: Request, db: Session = Depends(get_db), user: User = Depends(get_admin_user)):
    templates_map = {path.name: path.read_text(encoding="utf-8") for path in available_template_files()}
    return templates.TemplateResponse(
        "admin.html",
        template_context(
            request,
            user=user,
            hotels=db.query(Hotel).order_by(Hotel.name).all(),
            bus_stops=db.query(BusStop).order_by(BusStop.name).all(),
            schedules=db.query(Schedule).order_by(Schedule.season_label, Schedule.pickup_time).all(),
            reply_templates=templates_map,
            settings=settings,
        ),
    )


@router.get("/mailbox-status")
def admin_mailbox_status(user: User = Depends(get_admin_user)):
    return JSONResponse(mailbox_status())


@router.post("/hotels")
def create_hotel(
    name: str = Form(...),
    aliases: str = Form(""),
    bus_stop_id: int = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    db.add(Hotel(name=name, aliases=aliases, bus_stop_id=bus_stop_id))
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/hotels/{hotel_id}")
def update_hotel(
    hotel_id: int,
    name: str = Form(...),
    aliases: str = Form(""),
    bus_stop_id: int = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    hotel = db.query(Hotel).filter(Hotel.id == hotel_id).first()
    hotel.name = name
    hotel.aliases = aliases
    hotel.bus_stop_id = bus_stop_id
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
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    db.add(BusStop(name=name, address=address, latitude=latitude, longitude=longitude))
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/bus-stops/{stop_id}")
def update_stop(
    stop_id: int,
    name: str = Form(...),
    address: str = Form(...),
    latitude: float = Form(...),
    longitude: float = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    stop = db.query(BusStop).filter(BusStop.id == stop_id).first()
    stop.name = name
    stop.address = address
    stop.latitude = latitude
    stop.longitude = longitude
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
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    parsed_pickup_time = datetime.strptime(pickup_time, "%H:%M").time()
    db.add(
        Schedule(
            bus_stop_id=bus_stop_id,
            pickup_time=parsed_pickup_time,
            season_label=season_label,
            valid_from=datetime.strptime(valid_from, "%Y-%m-%d").date() if valid_from else None,
            valid_to=datetime.strptime(valid_to, "%Y-%m-%d").date() if valid_to else None,
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
    db: Session = Depends(get_db),
    user: User = Depends(get_admin_user),
):
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    schedule.bus_stop_id = bus_stop_id
    schedule.pickup_time = datetime.strptime(pickup_time, "%H:%M").time()
    schedule.season_label = season_label
    schedule.valid_from = datetime.strptime(valid_from, "%Y-%m-%d").date() if valid_from else None
    schedule.valid_to = datetime.strptime(valid_to, "%Y-%m-%d").date() if valid_to else None
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
    form = await request.form()
    content = form.get("content", "")
    path = REPLIES_DIR / template_name
    path.write_text(str(content), encoding="utf-8")
    return RedirectResponse(url="/admin", status_code=303)


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
    fuzzy_match_threshold: int = Form(...),
    secret_key: str = Form(...),
    safe_mode: str = Form("true"),
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
            "FUZZY_MATCH_THRESHOLD": str(fuzzy_match_threshold),
            "SECRET_KEY": secret_key,
            "SAFE_MODE": safe_mode,
        }
    )
    return RedirectResponse(url="/admin", status_code=303)
