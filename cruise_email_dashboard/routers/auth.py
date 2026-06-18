from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from cruise_email_dashboard.database.db import get_db
from cruise_email_dashboard.dependencies import template_context, templates
from cruise_email_dashboard.services.auth import authenticate_user
from cruise_email_dashboard.services.csrf import validate_csrf

router = APIRouter(dependencies=[Depends(validate_csrf)])


@router.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse("login.html", template_context(request))


@router.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = authenticate_user(db, username, password)
    if not user:
        return templates.TemplateResponse(
            "login.html",
            template_context(request, error="Invalid username or password."),
            status_code=400,
        )
    request.session["user_id"] = user.id
    return RedirectResponse(url="/", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
