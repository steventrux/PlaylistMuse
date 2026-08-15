"""Optional GitHub-backed check for whether a newer PlaylistMuse build exists."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import Any

import httpx

from backend.version import USER_AGENT

API_ROOT = "https://api.github.com/repos/steventrux/PlaylistMuse"
DEFAULT_TIMEOUT_SECONDS = 4.0
DEFAULT_CACHE_TTL_SECONDS = 10 * 60

LOGGER = logging.getLogger(__name__)
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}

_UNKNOWN_RESULT: dict[str, Any] = {
    "update_available": None,
    "latest": None,
    "url": None,
}


def _environment_ttl() -> float:
    raw = os.getenv("PLAYLISTMUSE_UPDATE_CHECK_TTL_SECONDS", "").strip()
    if not raw:
        return DEFAULT_CACHE_TTL_SECONDS
    try:
        return min(24 * 60 * 60, max(60.0, float(raw)))
    except ValueError:
        return DEFAULT_CACHE_TTL_SECONDS


def _environment_timeout() -> float:
    raw = os.getenv("PLAYLISTMUSE_UPDATE_CHECK_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return min(15.0, max(1.0, float(raw)))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _version_tuple(value: str) -> tuple[int, ...] | None:
    parts = value.strip().split(".")
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        return None


def _is_newer_version(latest: str, current: str) -> bool:
    latest_tuple = _version_tuple(latest)
    current_tuple = _version_tuple(current)
    if latest_tuple is not None and current_tuple is not None:
        return latest_tuple > current_tuple
    return latest != current


async def _check_stable(
    version: str,
    active_client: httpx.AsyncClient,
) -> dict[str, Any]:
    response = await active_client.get(f"{API_ROOT}/releases/latest")
    response.raise_for_status()
    payload = response.json()
    tag_name = str(payload.get("tag_name", "")).strip()
    latest_version = tag_name[1:] if tag_name.lower().startswith("v") else tag_name
    if not latest_version:
        return dict(_UNKNOWN_RESULT)
    return {
        "update_available": _is_newer_version(latest_version, version),
        "latest": latest_version,
        "url": payload.get("html_url"),
    }


async def _check_dev(
    commit_sha: str,
    active_client: httpx.AsyncClient,
) -> dict[str, Any]:
    response = await active_client.get(f"{API_ROOT}/commits/dev")
    response.raise_for_status()
    payload = response.json()
    latest_sha = str(payload.get("sha", "")).strip()
    if not latest_sha:
        return dict(_UNKNOWN_RESULT)
    html_url = payload.get("html_url")
    return {
        "update_available": latest_sha != commit_sha,
        "latest": latest_sha[:7],
        "url": html_url,
    }


async def check_for_update(
    *,
    channel: str,
    version: str,
    commit_sha: str,
    client: httpx.AsyncClient | None = None,
    now: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Return whether a newer build exists, or an "unknown" result if it can't be determined."""
    if channel not in {"stable", "dev"}:
        return dict(_UNKNOWN_RESULT)
    if channel == "stable" and not version.strip():
        return dict(_UNKNOWN_RESULT)
    if channel == "dev" and not commit_sha.strip():
        return dict(_UNKNOWN_RESULT)

    current_time = now()
    cached = _CACHE.get(channel)
    if cached and cached[0] > current_time:
        return dict(cached[1])

    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(_environment_timeout()),
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    try:
        if channel == "stable":
            result = await _check_stable(version, active_client)
        else:
            result = await _check_dev(commit_sha, active_client)
    except (httpx.HTTPError, ValueError, TypeError) as error:
        LOGGER.info("Update check unavailable: %s", error)
        result = dict(_UNKNOWN_RESULT)
    finally:
        if owns_client:
            await active_client.aclose()

    _CACHE[channel] = (now() + _environment_ttl(), dict(result))
    return result


def _clear_cache() -> None:
    """Clear the in-memory cache for tests."""
    _CACHE.clear()
