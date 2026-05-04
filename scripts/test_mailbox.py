from __future__ import annotations

import imaplib
import smtplib
import sys
from pathlib import Path

from dotenv import load_dotenv
import os


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")


def env_value(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def print_failure(service: str, exc: Exception, host: str, port: int, username: str) -> None:
    print(f"[{service}] FAILURE: {exc}")
    print(f"[{service}] Credentials used: host={host} port={port} username={username}")


def test_imap(host: str, port: int, username: str, password: str) -> bool:
    print("[IMAP] Connecting...")
    mailbox = None
    try:
        mailbox = imaplib.IMAP4_SSL(host, port, timeout=10)
        print("[IMAP] Connected")
        print("[IMAP] Logging in...")
        mailbox.login(username, password)
        print("[IMAP] Login successful")
        print("[IMAP] Selecting INBOX...")
        status, data = mailbox.select("INBOX")
        print(f"[IMAP] INBOX selected: status={status}")
        print("[IMAP] Fetching unread count...")
        status, data = mailbox.search(None, "UNSEEN")
        unread_count = len(data[0].split()) if data and data[0] else 0
        print(f"[IMAP] Unread count: {unread_count}")
        print("[IMAP] Logging out...")
        mailbox.logout()
        mailbox = None
        print("[IMAP] Logged out")
        return True
    except Exception as exc:
        print_failure("IMAP", exc, host, port, username)
        return False
    finally:
        if mailbox is not None:
            try:
                mailbox.logout()
            except Exception:
                pass


def test_smtp(host: str, port: int, username: str, password: str) -> bool:
    print("[SMTP] Connecting...")
    server = None
    try:
        server = smtplib.SMTP_SSL(host, port, timeout=10)
        print("[SMTP] Connected")
        print("[SMTP] Logging in...")
        server.login(username, password)
        print("[SMTP] Login successful")
        print("[SMTP] NOOP...")
        code, response = server.noop()
        print(f"[SMTP] NOOP response: {code} {response!r}")
        print("[SMTP] Quitting...")
        server.quit()
        server = None
        print("[SMTP] Quit complete")
        return True
    except Exception as exc:
        print_failure("SMTP", exc, host, port, username)
        return False
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass


def main() -> int:
    imap_host = env_value("IMAP_HOST")
    imap_port = int(env_value("IMAP_PORT", "993"))
    imap_user = env_value("IMAP_USER")
    imap_password = env_value("IMAP_PASSWORD")

    smtp_host = env_value("SMTP_HOST")
    smtp_port = int(env_value("SMTP_PORT", "465"))
    smtp_user = env_value("SMTP_USER")
    smtp_password = env_value("SMTP_PASSWORD")

    print("Mailbox diagnostic starting")
    imap_ok = test_imap(imap_host, imap_port, imap_user, imap_password)
    smtp_ok = test_smtp(smtp_host, smtp_port, smtp_user, smtp_password)
    success = imap_ok and smtp_ok
    print(f"Mailbox diagnostic result: {'SUCCESS' if success else 'FAILURE'}")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
