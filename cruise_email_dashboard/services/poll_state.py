from __future__ import annotations

import json
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
POLL_STATE_PATH = DATA_DIR / "poll_state.json"

DEFAULT_POLL_STATE = {
    "last_attempt": None,
    "last_success": None,
    "last_error": "",
    "backoff_active": False,
    "consecutive_failures": 0,
}


def ensure_poll_state_file() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not POLL_STATE_PATH.exists():
        POLL_STATE_PATH.write_text(json.dumps(DEFAULT_POLL_STATE, indent=2), encoding="utf-8")


def load_poll_state() -> dict[str, Any]:
    ensure_poll_state_file()
    state = json.loads(POLL_STATE_PATH.read_text(encoding="utf-8"))
    return {**DEFAULT_POLL_STATE, **state}


def save_poll_state(state: dict[str, Any]) -> dict[str, Any]:
    ensure_poll_state_file()
    merged = {**DEFAULT_POLL_STATE, **state}
    POLL_STATE_PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return merged


def update_poll_state(**updates: Any) -> dict[str, Any]:
    state = load_poll_state()
    state.update(updates)
    return save_poll_state(state)


def reset_backoff_state() -> dict[str, Any]:
    return update_poll_state(backoff_active=False, consecutive_failures=0, last_error="")
