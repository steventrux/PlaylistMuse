"""Persistent Last.fm API-key settings."""

from __future__ import annotations

import os
import re
from typing import Any

import httpx

from backend.config import DATA_DIR
from backend.storage import delete_file, read_json_object, write_secure_json

LASTFM_SETTINGS_PATH = DATA_DIR / "lastfm.json"
LASTFM_API_ROOT = "https://ws.audioscrobbler.com/2.0/"
LASTFM_VALIDATION_TIMEOUT_SECONDS = 8.0
_LASTFM_API_KEY_RE = re.compile(r"[0-9a-fA-F]{32}\Z")


def _normalize_api_key(api_key: str) -> str:
    normalized = str(api_key or "").strip()
    if not _LASTFM_API_KEY_RE.fullmatch(normalized):
        raise ValueError("Enter a valid 32-character Last.fm API key.")
    return normalized


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


async def validate_lastfm_api_key(
    api_key: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Verify a saved key with Last.fm before reporting it as configured."""
    normalized = _normalize_api_key(api_key)
    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(LASTFM_VALIDATION_TIMEOUT_SECONDS),
        headers={"User-Agent": "PlaylistMuse/0.7"},
    )
    try:
        response = await active_client.get(
            LASTFM_API_ROOT,
            params={
                "method": "chart.getTopArtists",
                "api_key": normalized,
                "limit": "1",
                "format": "json",
            },
        )
        response.raise_for_status()
        payload: Any = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Last.fm returned an invalid validation response.")
        if payload.get("error"):
            raise ValueError(
                "Last.fm rejected this API key. Check the key and try again."
            )
        if not isinstance(payload.get("artists"), dict):
            raise ValueError("Last.fm could not validate this API key.")
        return normalized
    finally:
        if owns_client:
            await active_client.aclose()


def save_lastfm_api_key(api_key: str) -> dict[str, object]:
    normalized = _normalize_api_key(api_key)
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
