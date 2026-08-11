"""Optional Last.fm recommendation enrichment for seed-based playlists."""

from __future__ import annotations

import hashlib
import logging
import os
import time
from collections.abc import Callable
from typing import Any

import httpx

from backend.lastfm_enrichment import enrich_lastfm_candidates
from backend.lastfm_settings import lastfm_api_key
from backend.version import USER_AGENT

API_ROOT = "https://ws.audioscrobbler.com/2.0/"
DEFAULT_TIMEOUT_SECONDS = 4.0
DEFAULT_CACHE_TTL_SECONDS = 6 * 60 * 60
MAX_SIMILAR_TRACKS = 100
MAX_CACHE_ENTRIES = 256

LOGGER = logging.getLogger(__name__)
_CACHE: dict[tuple[str, str, str, int], tuple[float, list[dict[str, str]]]] = {}


def _configured_api_key() -> str:
    return lastfm_api_key()


def _environment_timeout() -> float:
    raw = os.getenv("PLAYLISTMUSE_LASTFM_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return min(15.0, max(1.0, float(raw)))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _api_key_fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]


def _artist_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name", "")).strip()
    return str(value or "").strip()


def _candidate(
    track: dict[str, Any],
    seed_artist: str,
    seed_title: str,
) -> dict[str, str] | None:
    title = str(track.get("name", "")).strip()
    artist = _artist_name(track.get("artist"))
    if not title or not artist:
        return None
    if (
        title.casefold() == seed_title.casefold()
        and artist.casefold() == seed_artist.casefold()
    ):
        return None
    return {
        "artist": artist,
        "title": title,
        "description": (
            "A data-backed recommendation associated with the reference track by "
            "Last.fm listeners."
        ),
        "reason": (
            "It broadens the playlist with a listening-pattern match while preserving "
            "the seed track's musical direction."
        ),
        "source": "lastfm",
    }


def _parse_candidates(
    payload: Any,
    seed_artist: str,
    seed_title: str,
) -> list[dict[str, str]]:
    if not isinstance(payload, dict) or payload.get("error"):
        return []
    similar = payload.get("similartracks")
    if not isinstance(similar, dict):
        return []
    raw_tracks = similar.get("track")
    if isinstance(raw_tracks, dict):
        raw_tracks = [raw_tracks]
    if not isinstance(raw_tracks, list):
        return []

    candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw_tracks:
        if not isinstance(item, dict):
            continue
        candidate = _candidate(item, seed_artist, seed_title)
        if not candidate:
            continue
        key = (candidate["artist"].casefold(), candidate["title"].casefold())
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates


async def _finalize_candidates(
    seed_artist: str,
    seed_title: str,
    candidates: list[dict[str, str]],
    *,
    enrich_explanations: bool,
) -> list[dict[str, str]]:
    copies = [dict(candidate) for candidate in candidates]
    if not enrich_explanations:
        return copies
    return await enrich_lastfm_candidates(
        seed_artist,
        seed_title,
        copies,
    )


async def similar_track_candidates(
    artist: str,
    track: str,
    limit: int = 40,
    *,
    api_key: str | None = None,
    client: httpx.AsyncClient | None = None,
    now: Callable[[], float] = time.monotonic,
) -> list[dict[str, str]]:
    """Return similar tracks, or an empty list when enrichment is unavailable."""
    seed_artist = " ".join(str(artist).split())
    seed_title = " ".join(str(track).split())
    key = (api_key if api_key is not None else _configured_api_key()).strip()
    if not key or not seed_artist or not seed_title:
        return []

    normalized_limit = min(MAX_SIMILAR_TRACKS, max(1, int(limit)))
    cache_key = (
        _api_key_fingerprint(key),
        seed_artist.casefold(),
        seed_title.casefold(),
        normalized_limit,
    )
    cached = _CACHE.get(cache_key)
    current_time = now()
    enrich_explanations = api_key is None and client is None
    if cached and cached[0] > current_time:
        return await _finalize_candidates(
            seed_artist,
            seed_title,
            cached[1],
            enrich_explanations=enrich_explanations,
        )

    params = {
        "method": "track.getsimilar",
        "artist": seed_artist,
        "track": seed_title,
        "api_key": key,
        "autocorrect": "1",
        "limit": str(normalized_limit),
        "format": "json",
    }
    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(_environment_timeout()),
        headers={"User-Agent": USER_AGENT},
    )
    try:
        response = await active_client.get(API_ROOT, params=params)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("error"):
            LOGGER.info(
                "Last.fm enrichment rejected the request: %s",
                payload.get("message", payload.get("error")),
            )
            return []
        candidates = _parse_candidates(payload, seed_artist, seed_title)
    except (httpx.HTTPError, ValueError, TypeError) as error:
        LOGGER.info("Last.fm enrichment unavailable: %s", error)
        return []
    finally:
        if owns_client:
            await active_client.aclose()

    expired_keys = [key for key, value in _CACHE.items() if value[0] <= current_time]
    for expired_key in expired_keys:
        _CACHE.pop(expired_key, None)
    while len(_CACHE) >= MAX_CACHE_ENTRIES:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[cache_key] = (
        now() + DEFAULT_CACHE_TTL_SECONDS,
        [dict(candidate) for candidate in candidates],
    )
    return await _finalize_candidates(
        seed_artist,
        seed_title,
        candidates,
        enrich_explanations=enrich_explanations,
    )


def _clear_cache() -> None:
    """Clear the in-memory cache for tests."""
    _CACHE.clear()
