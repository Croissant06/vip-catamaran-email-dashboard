from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from cruise_email_dashboard.database.db import get_db
from cruise_email_dashboard.database.models import User, UserRole
from cruise_email_dashboard.services.auth import current_user
from cruise_email_dashboard.services.csrf import ensure_csrf_token
from cruise_email_dashboard.settings import settings

templates = Jinja2Templates(directory="cruise_email_dashboard/templates")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    return current_user(request, db)


def get_admin_user(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    return user


def template_context(request: Request, user: User | None = None, **kwargs):
    return {
        "request": request,
        "current_user": user,
        "active_path": request.url.path,
        "demo_mode": settings.demo_mode,
        "demo_email": settings.demo_email,
        "csrf_token": ensure_csrf_token(request),
        **kwargs,
    }
