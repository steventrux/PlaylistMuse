"""Optional short audio-preview lookup for tracks, backed by the Deezer search API."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from typing import Any

import httpx
from fastapi import APIRouter, Query

from backend.version import USER_AGENT

API_ROOT = "https://api.deezer.com/search"
DEFAULT_TIMEOUT_SECONDS = 4.0
DEFAULT_CACHE_TTL_SECONDS = 6 * 60 * 60
MAX_CACHE_ENTRIES = 512
SEARCH_RESULT_LIMIT = 5
_ARTIST_SPLIT_RE = re.compile(r",|&|\bfeat\.?\b|\bft\.?\b|\bwith\b", re.IGNORECASE)

LOGGER = logging.getLogger("playlistmuse.track_preview")
_CACHE: dict[tuple[str, str], tuple[float, str | None]] = {}

router = APIRouter(prefix="/tracks", tags=["track-preview"])


def _normalized(value: str) -> str:
    return " ".join(str(value or "").split())


def _artist_name_parts(value: str) -> list[str]:
    return [part.strip().casefold() for part in _ARTIST_SPLIT_RE.split(value) if part.strip()]


def _artist_matches(requested_artist: str, candidate_artist: str) -> bool:
    candidate = candidate_artist.strip().casefold()
    if not candidate:
        return False
    return any(
        part and (part in candidate or candidate in part)
        for part in _artist_name_parts(requested_artist)
    )


def _extract_preview_url(payload: Any, requested_artist: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    results = payload.get("data")
    if not isinstance(results, list):
        return None
    for result in results:
        if not isinstance(result, dict):
            continue
        candidate_artist = result.get("artist")
        candidate_artist_name = (
            candidate_artist.get("name") if isinstance(candidate_artist, dict) else None
        )
        if not isinstance(candidate_artist_name, str):
            continue
        if not _artist_matches(requested_artist, candidate_artist_name):
            continue
        preview = result.get("preview")
        if isinstance(preview, str) and preview:
            return preview
    return None


async def find_preview_url(
    title: str,
    artist: str,
    *,
    client: httpx.AsyncClient | None = None,
    now: Callable[[], float] = time.monotonic,
) -> str | None:
    """Return a short preview audio URL for a track, or None when unavailable."""
    normalized_title = _normalized(title)
    normalized_artist = _normalized(artist)
    if not normalized_title or not normalized_artist:
        return None

    cache_key = (normalized_artist.casefold(), normalized_title.casefold())
    cached = _CACHE.get(cache_key)
    current_time = now()
    if cached and cached[0] > current_time:
        return cached[1]

    params = {"q": f"{normalized_artist} {normalized_title}", "limit": str(SEARCH_RESULT_LIMIT)}
    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(DEFAULT_TIMEOUT_SECONDS),
        headers={"User-Agent": USER_AGENT},
    )
    preview_url: str | None = None
    try:
        response = await active_client.get(API_ROOT, params=params)
        response.raise_for_status()
        preview_url = _extract_preview_url(response.json(), normalized_artist)
    except (httpx.HTTPError, ValueError, TypeError) as error:
        LOGGER.info("Deezer preview lookup unavailable for %r by %r: %s", title, artist, error)
        return None
    finally:
        if owns_client:
            await active_client.aclose()

    expired_keys = [key for key, value in _CACHE.items() if value[0] <= current_time]
    for expired_key in expired_keys:
        _CACHE.pop(expired_key, None)
    while len(_CACHE) >= MAX_CACHE_ENTRIES:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[cache_key] = (now() + DEFAULT_CACHE_TTL_SECONDS, preview_url)
    return preview_url


@router.get("/preview")
async def get_track_preview(
    title: str = Query(..., min_length=1),
    artist: str = Query(..., min_length=1),
) -> dict[str, str | None]:
    """Return a short preview audio URL for a track, or null when none is available."""
    return {"preview_url": await find_preview_url(title, artist)}


def _clear_cache() -> None:
    """Clear the in-memory cache for tests."""
    _CACHE.clear()
