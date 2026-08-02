"""Persistent Last.fm API-key settings."""

from __future__ import annotations

import os

from backend.config import DATA_DIR
from backend.storage import delete_file, read_json_object, write_secure_json

LASTFM_SETTINGS_PATH = DATA_DIR / "lastfm.json"


def _saved_api_key() -> str:
    values = read_json_object(LASTFM_SETTINGS_PATH)
    return str(values.get("api_key", "") or "").strip()


def _environment_api_key() -> str:
    return os.getenv("PLAYLISTMUSE_LASTFM_API_KEY", "").strip()


def lastfm_api_key() -> str:
    """Return the saved key, falling back to the environment configuration."""
    return _saved_api_key() or _environment_api_key()


def lastfm_settings_response() -> dict[str, object]:
    saved = bool(_saved_api_key())
    environment = bool(_environment_api_key())
    source = "saved" if saved else "environment" if environment else ""
    return {
        "configured": saved or environment,
        "api_key_set": saved or environment,
        "source": source,
    }


def save_lastfm_api_key(api_key: str) -> dict[str, object]:
    normalized = str(api_key or "").strip()
    if len(normalized) < 8:
        raise ValueError("Enter a valid Last.fm API key.")
    if len(normalized) > 256:
        raise ValueError("The Last.fm API key is too long.")

    write_secure_json(
        LASTFM_SETTINGS_PATH,
        {"api_key": normalized},
        temporary_path=LASTFM_SETTINGS_PATH.with_suffix(".tmp"),
    )
    return lastfm_settings_response()


def disconnect_lastfm() -> dict[str, object]:
    """Remove the saved key; an environment key remains active when present."""
    delete_file(LASTFM_SETTINGS_PATH)
    return lastfm_settings_response()
