from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, status

CSRF_SESSION_KEY = "csrf_token"
CSRF_HEADER_NAME = "x-csrf-token"
CSRF_FORM_FIELD = "csrf_token"
CSRF_ERROR_MESSAGE = "Invalid or missing CSRF token."


def ensure_csrf_token(request: Request) -> str:
    token = request.session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return token


async def validate_csrf(request: Request) -> None:
    if request.method.upper() != "POST":
        return

    expected_token = ensure_csrf_token(request)
    provided_token = request.headers.get(CSRF_HEADER_NAME, "").strip()

    if not provided_token:
        content_type = request.headers.get("content-type", "").lower()
        if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
            form = await request.form()
            provided_token = str(form.get(CSRF_FORM_FIELD, "")).strip()

    if not provided_token or not secrets.compare_digest(provided_token, expected_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=CSRF_ERROR_MESSAGE)
