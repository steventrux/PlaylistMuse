"""Opt-in, anonymous "a playlist was generated" ping for the public aggregate counter.

Off by default. When enabled, each successful generation sends a single HTTP request
with no body, no query parameters, and no identifying data whatsoever -- no
installation ID, no version, no prompt or playlist content. Every outcome (including
failures, which are swallowed) is logged locally at INFO level so anyone who enables
this can always see exactly what happened, without having to trust it blindly.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from backend.config import DATA_DIR
from backend.storage import read_json_object, write_secure_json
from backend.version import USER_AGENT

TELEMETRY_PATH = DATA_DIR / "telemetry.json"
# No default on purpose: this only becomes a real endpoint once the aggregator
# (stats-service/) is deployed and its URL is set here via env var. Until then,
# report_playlist_generated() is a no-op even if a user opts in.
TELEMETRY_ENDPOINT = os.getenv("PLAYLISTMUSE_TELEMETRY_URL", "").strip()
REQUEST_TIMEOUT_SECONDS = 3.0

LOGGER = logging.getLogger("playlistmuse.telemetry")


def telemetry_settings_response() -> dict[str, Any]:
    """Return the current opt-in state."""
    values = read_json_object(TELEMETRY_PATH)
    return {"enabled": bool(values.get("enabled", False))}


def telemetry_enabled() -> bool:
    return bool(read_json_object(TELEMETRY_PATH).get("enabled", False))


def set_telemetry_enabled(enabled: bool) -> dict[str, Any]:
    write_secure_json(TELEMETRY_PATH, {"enabled": bool(enabled)})
    return telemetry_settings_response()


async def report_playlist_generated(client: httpx.AsyncClient | None = None) -> None:
    """Fire-and-forget: never raises, never delays the caller, never blocks generation."""
    if not TELEMETRY_ENDPOINT:
        return
    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS),
        headers={"User-Agent": USER_AGENT},
    )
    try:
        response = await active_client.post(TELEMETRY_ENDPOINT)
        response.raise_for_status()
        LOGGER.info("telemetry ping sent to %s", TELEMETRY_ENDPOINT)
    except (httpx.HTTPError, ValueError, TypeError) as error:
        LOGGER.info("telemetry ping failed (ignored): %s", error)
    finally:
        if owns_client:
            await active_client.aclose()
