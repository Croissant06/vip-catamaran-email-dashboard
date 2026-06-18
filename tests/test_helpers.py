from __future__ import annotations

import re

from fastapi.testclient import TestClient


def extract_csrf_token(html: str) -> str | None:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    if match:
        return match.group(1)
    meta_match = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
    if meta_match:
        return meta_match.group(1)
    return None


def login_with_csrf(client: TestClient, username: str, password: str) -> None:
    login_page = client.get("/login")
    assert login_page.status_code == 200
    csrf_token = extract_csrf_token(login_page.text)
    assert csrf_token

    response = client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": csrf_token},
        follow_redirects=True,
    )
    assert response.status_code == 200
