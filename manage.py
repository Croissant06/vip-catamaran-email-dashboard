from __future__ import annotations

import sys

from cruise_email_dashboard.database.db import init_db, session_scope
from cruise_email_dashboard.database.models import User, UserRole
from cruise_email_dashboard.services.auth import hash_password


def create_admin() -> None:
    init_db()
    username = input("Username: ").strip()
    password = input("Password: ").strip()
    with session_scope() as db:
        if db.query(User).filter(User.username == username).first():
            print("User already exists.")
            return
        db.add(User(username=username, hashed_password=hash_password(password), role=UserRole.admin))
    print("Admin user created.")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "create_admin":
        create_admin()
    else:
        print("Usage: python manage.py create_admin")
