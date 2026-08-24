"""Optional Last.fm track-tag evidence for playlist-wide creative-fit evaluation."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from backend.lastfm import API_ROOT, _environment_timeout
from backend.lastfm_settings import lastfm_api_key
from backend.version import USER_AGENT

LOGGER = logging.getLogger("playlistmuse.lastfm.tags")
CACHE_TTL_SECONDS = 6 * 60 * 60
MAX_CACHE_ENTRIES = 512
MAX_TRACK_TAGS = 8
MAX_CONCURRENT_REQUESTS = 8

_CACHE: dict[tuple[str, str, str], tuple[float, LastfmTagEvidence]] = {}


@dataclass(frozen=True, slots=True)
class LastfmTagEvidence:
    """Track-specific community tag evidence for one catalogue identity.

    ``artist_tags`` is retained as a compatibility field but is intentionally never
    populated. Artist-level Last.fm tags proved too noisy for song-level creative fit.
    """

    track_tags: tuple[str, ...] = ()
    artist_tags: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return bool(self.track_tags)


def _normalize(value: str) -> str:
    return " ".join(str(value).casefold().split()).strip()


def _api_key_fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]


def _cache_key(api_key: str, artist: str, title: str) -> tuple[str, str, str]:
    return (
        _api_key_fingerprint(api_key),
        _normalize(artist),
        _normalize(title),
    )


def _clean_tags(payload: Any, *, limit: int = MAX_TRACK_TAGS) -> tuple[str, ...]:
    if not isinstance(payload, dict):
        return ()
    top_tags = payload.get("toptags")
    if not isinstance(top_tags, dict):
        return ()
    raw = top_tags.get("tag", [])
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return ()

    tags: list[str] = []
    seen: set[str] = set()
    for item in raw:
        name = str(item.get("name", "")).strip() if isinstance(item, dict) else ""
        key = _normalize(name)
        if not name or not key or key in seen:
            continue
        seen.add(key)
        tags.append(name[:80])
        if len(tags) >= limit:
            break
    return tuple(tags)


def _prune_cache(now: float) -> None:
    expired = [key for key, value in _CACHE.items() if value[0] <= now]
    for key in expired:
        _CACHE.pop(key, None)
    while len(_CACHE) >= MAX_CACHE_ENTRIES:
        _CACHE.pop(next(iter(_CACHE)))


async def _request_track_tags(
    client: httpx.AsyncClient,
    api_key: str,
    *,
    artist: str,
    title: str,
) -> tuple[str, ...] | None:
    response = await client.get(
        API_ROOT,
        params={
            "method": "track.gettoptags",
            "api_key": api_key,
            "artist": artist,
            "track": title,
            "autocorrect": "1",
            "format": "json",
        },
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("error") is not None:
        return None
    return _clean_tags(payload)


async def track_tag_evidence(
    artist: str,
    title: str,
    *,
    api_key: str | None = None,
    client: httpx.AsyncClient | None = None,
    now: Callable[[], float] = time.monotonic,
) -> LastfmTagEvidence:
    """Return only track-specific Last.fm tags; missing tags remain neutral."""
    normalized_artist = " ".join(str(artist).split()).strip()
    normalized_title = " ".join(str(title).split()).strip()
    key = (api_key if api_key is not None else lastfm_api_key()).strip()
    if not key or not normalized_artist or not normalized_title:
        return LastfmTagEvidence()

    current_time = now()
    cache_key = _cache_key(key, normalized_artist, normalized_title)
    cached = _CACHE.get(cache_key)
    if cached and cached[0] > current_time:
        return cached[1]

    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(_environment_timeout()),
        headers={"User-Agent": USER_AGENT},
    )
    try:
        track_tags = await _request_track_tags(
            active_client,
            key,
            artist=normalized_artist,
            title=normalized_title,
        )
        if track_tags is None:
            return LastfmTagEvidence()

        evidence = LastfmTagEvidence(track_tags=track_tags)
        _prune_cache(current_time)
        _CACHE[cache_key] = (now() + CACHE_TTL_SECONDS, evidence)
        return evidence
    except (httpx.HTTPError, ValueError, TypeError) as error:
        LOGGER.info(
            "Last.fm track-tag evidence unavailable for %s — %s: %s",
            normalized_artist,
            normalized_title,
            error,
        )
        return LastfmTagEvidence()
    finally:
        if owns_client:
            await active_client.aclose()


async def tag_evidence_for_tracks(
    tracks: list[dict[str, Any]],
) -> list[LastfmTagEvidence]:
    """Fetch optional track-level Last.fm evidence without blocking on failures."""
    key = lastfm_api_key().strip()
    if not key or not tracks:
        return [LastfmTagEvidence() for _ in tracks]

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async def one(
        client: httpx.AsyncClient,
        track: dict[str, Any],
    ) -> LastfmTagEvidence:
        artist = str(track.get("artist") or track.get("artists") or "").strip()
        title = str(track.get("title") or "").strip()
        async with semaphore:
            return await track_tag_evidence(
                artist,
                title,
                api_key=key,
                client=client,
            )

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(_environment_timeout()),
        headers={"User-Agent": USER_AGENT},
    ) as client:
        results = await asyncio.gather(
            *(one(client, track) for track in tracks),
            return_exceptions=True,
        )

    return [
        result if isinstance(result, LastfmTagEvidence) else LastfmTagEvidence()
        for result in results
    ]


def _clear_cache() -> None:
    """Clear the in-memory tag cache for tests."""
    _CACHE.clear()
