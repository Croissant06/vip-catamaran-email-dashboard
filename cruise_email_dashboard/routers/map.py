from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, joinedload

from cruise_email_dashboard.database.db import get_db
from cruise_email_dashboard.database.models import BusStop, Hotel, User
from cruise_email_dashboard.dependencies import get_current_user, template_context, templates
from cruise_email_dashboard.services.scheduler import resolve_pickup_schedule

router = APIRouter(prefix="/map", tags=["map"])


@router.get("")
def map_page(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return templates.TemplateResponse("map.html", template_context(request, user=user))


@router.get("/data")
def map_data(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    stops = db.query(BusStop).options(joinedload(BusStop.hotels)).all()
    hotels = db.query(Hotel).options(joinedload(Hotel.bus_stop)).all()

    payload = {
        "bus_stops": [
            {
                "id": stop.id,
                "name": stop.name,
                "address": stop.address,
                "latitude": stop.latitude,
                "longitude": stop.longitude,
                "pickup_time": (resolve_pickup_schedule(db, stop).schedule.pickup_time.strftime("%H:%M") if resolve_pickup_schedule(db, stop).schedule else "N/A"),
                "maps_url": stop.maps_url,
                "description": stop.description,
                "vehicle_type": stop.vehicle_type.value,
            }
            for stop in stops
        ],
        "hotels": [
            {
                "id": hotel.id,
                "name": hotel.name,
                "latitude": hotel.bus_stop.latitude + 0.003 if hotel.bus_stop else 0,
                "longitude": hotel.bus_stop.longitude + 0.003 if hotel.bus_stop else 0,
                "bus_stop_id": hotel.bus_stop.id if hotel.bus_stop else None,
            }
            for hotel in hotels
            if hotel.bus_stop
        ],
    }
    return JSONResponse(payload)
