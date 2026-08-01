"""Persistent first-run onboarding state for PlaylistMuse."""

from __future__ import annotations

from typing import Any

from backend.config import DATA_DIR
from backend.storage import read_json_object, write_secure_json

ONBOARDING_PATH = DATA_DIR / "onboarding.json"


def onboarding_status() -> dict[str, bool]:
    """Return whether the initial setup wizard still needs to be shown."""
    values = read_json_object(ONBOARDING_PATH)
    return {"required": not bool(values.get("shown"))}


def acknowledge_onboarding() -> dict[str, Any]:
    """Persist that the initial setup wizard has already been presented."""
    write_secure_json(ONBOARDING_PATH, {"shown": True})
    return {"required": False}
