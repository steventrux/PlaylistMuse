"""Last.fm discovery signals used as evidence by seed-based playlist generation."""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from collections.abc import Callable
from typing import Any

import httpx

from backend.lastfm import (
    API_ROOT,
    DEFAULT_CACHE_TTL_SECONDS,
    MAX_CACHE_ENTRIES,
    USER_AGENT,
    _api_key_fingerprint,
    _environment_timeout,
)
from backend.lastfm_settings import lastfm_api_key

LOGGER = logging.getLogger("playlistmuse.lastfm.discovery")
MAX_CONTEXT_SIGNALS = 60
MAX_PROMPT_ANCHORS = 3
MAX_SIMILAR_ARTISTS = 12
ARTIST_SIGNAL_TITLE = "Choose a suitable track by this artist"

_CACHE: dict[tuple[str, str, str, int], tuple[float, list[dict[str, str]]]] = {}


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value).casefold())
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[a-z0-9]+", without_marks))


def _key(artist: str, title: str = "") -> tuple[str, str]:
    return (_normalize(artist), _normalize(title))


def _artist_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name", "")).strip()
    return str(value or "").strip()


def _track_signal(
    artist: str,
    title: str,
    *,
    match: str = "",
) -> dict[str, str] | None:
    normalized_artist = " ".join(str(artist).split())
    normalized_title = " ".join(str(title).split())
    if not normalized_artist or not normalized_title:
        return None
    return {
        "artist": normalized_artist,
        "title": normalized_title,
        "source": "lastfm",
        "lastfm_strategy": "similar_track",
        "lastfm_match": str(match or "").strip(),
    }


def _artist_signal(artist: str, *, match: str = "") -> dict[str, str] | None:
    normalized_artist = " ".join(str(artist).split())
    if not normalized_artist:
        return None
    return {
        "artist": normalized_artist,
        "title": ARTIST_SIGNAL_TITLE,
        "source": "lastfm",
        "lastfm_strategy": "similar_artist",
        "lastfm_match": str(match or "").strip(),
    }


def _deduplicate(
    signals: list[dict[str, str]],
    *,
    excluded: set[tuple[str, str]] | None = None,
    limit: int = MAX_CONTEXT_SIGNALS,
) -> list[dict[str, str]]:
    unique: list[dict[str, str]] = []
    seen = set(excluded or set())
    for signal in signals:
        identity = _key(signal.get("artist", ""), signal.get("title", ""))
        if not identity[0] or identity in seen:
            continue
        seen.add(identity)
        unique.append(signal)
        if len(unique) >= max(1, min(MAX_CONTEXT_SIGNALS, limit)):
            break
    return unique


def select_prompt_anchors(
    tracks: list[dict[str, str]],
    *,
    max_anchors: int = MAX_PROMPT_ANCHORS,
) -> list[dict[str, str]]:
    """Return distinct first-pass songs for diagnostics and compatibility."""
    selected: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    normalized_max = max(1, min(MAX_PROMPT_ANCHORS, int(max_anchors)))
    for track in tracks:
        artist = " ".join(str(track.get("artist", "")).split())
        title = " ".join(str(track.get("title", "")).split())
        identity = _key(artist, title)
        if not all(identity) or identity in seen:
            continue
        seen.add(identity)
        selected.append({"artist": artist, "title": title})
        if len(selected) >= normalized_max:
            break
    return selected


def _attach_anchor(
    signals: list[dict[str, str]],
    artist: str,
    title: str,
) -> list[dict[str, str]]:
    annotated: list[dict[str, str]] = []
    for signal in signals:
        copy = dict(signal)
        copy["anchor_artist"] = artist
        copy["anchor_title"] = title
        annotated.append(copy)
    return annotated


async def _request(
    client: httpx.AsyncClient,
    api_key: str,
    method: str,
    **params: str,
) -> dict[str, Any]:
    response = await client.get(
        API_ROOT,
        params={
            "method": method,
            "api_key": api_key,
            "autocorrect": "1",
            "format": "json",
            **params,
        },
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        return {}
    if payload.get("error"):
        LOGGER.info(
            "Last.fm discovery method %s returned %s",
            method,
            payload.get("message", payload.get("error")),
        )
        return {}
    return payload


def _parse_similar_tracks(
    payload: dict[str, Any],
    seed_artist: str,
    seed_title: str,
) -> list[dict[str, str]]:
    raw_tracks = payload.get("similartracks", {}).get("track", [])
    if isinstance(raw_tracks, dict):
        raw_tracks = [raw_tracks]
    if not isinstance(raw_tracks, list):
        return []

    seed_key = _key(seed_artist, seed_title)
    signals: list[dict[str, str]] = []
    for item in raw_tracks:
        if not isinstance(item, dict):
            continue
        signal = _track_signal(
            _artist_name(item.get("artist")),
            str(item.get("name", "")),
            match=str(item.get("match", "")),
        )
        if signal and _key(signal["artist"], signal["title"]) != seed_key:
            signals.append(signal)
    return _deduplicate(signals, excluded={seed_key})


def _parse_similar_artists(
    payload: dict[str, Any],
    seed_artist: str,
) -> list[dict[str, str]]:
    raw_artists = payload.get("similarartists", {}).get("artist", [])
    if isinstance(raw_artists, dict):
        raw_artists = [raw_artists]
    if not isinstance(raw_artists, list):
        return []

    seed_artist_key = _normalize(seed_artist)
    signals: list[dict[str, str]] = []
    for item in raw_artists:
        if not isinstance(item, dict):
            continue
        signal = _artist_signal(
            str(item.get("name", "")),
            match=str(item.get("match", "")),
        )
        if signal and _normalize(signal["artist"]) != seed_artist_key:
            signals.append(signal)
    return _deduplicate(signals, limit=MAX_SIMILAR_ARTISTS)


def _store_cache(
    cache_key: tuple[str, str, str, int],
    result: list[dict[str, str]],
    current_time: float,
) -> None:
    expired = [key for key, value in _CACHE.items() if value[0] <= current_time]
    for key in expired:
        _CACHE.pop(key, None)
    while len(_CACHE) >= MAX_CACHE_ENTRIES:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[cache_key] = (
        current_time + DEFAULT_CACHE_TTL_SECONDS,
        [dict(item) for item in result],
    )


def _clear_cache() -> None:
    """Clear the in-memory cache for tests."""
    _CACHE.clear()


async def discover_for_seed(
    artist: str,
    title: str,
    *,
    limit: int = 40,
    broaden: bool = False,
    api_key: str | None = None,
    client: httpx.AsyncClient | None = None,
    now: Callable[[], float] = time.monotonic,
) -> list[dict[str, str]]:
    """Return track evidence, falling back to related-artist signals for the AI.

    When `broaden` is True, related-artist signals are blended in alongside the direct
    track-level matches (not just used as a fallback when there are none) -- this widens
    the evidence pool for exploratory seed generation, which needs genuine breadth beyond
    the seed's closest sonic neighbours to have material to draw from.
    """
    seed_artist = " ".join(str(artist).split())
    seed_title = " ".join(str(title).split())
    key = (api_key if api_key is not None else lastfm_api_key()).strip()
    normalized_limit = max(1, min(MAX_CONTEXT_SIGNALS, int(limit)))
    if not key or not seed_artist or not seed_title:
        return []

    cache_key = (
        _api_key_fingerprint(key),
        seed_artist.casefold(),
        seed_title.casefold(),
        normalized_limit,
        broaden,
    )
    current_time = now()
    cached = _CACHE.get(cache_key)
    if cached and cached[0] > current_time:
        return [dict(item) for item in cached[1]]

    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(_environment_timeout()),
        headers={"User-Agent": USER_AGENT},
    )
    try:
        similar_payload = await _request(
            active_client,
            key,
            "track.getsimilar",
            artist=seed_artist,
            track=seed_title,
            limit=str(normalized_limit),
        )
        track_call_failed = not similar_payload
        direct = _parse_similar_tracks(similar_payload, seed_artist, seed_title)
        if direct and not broaden:
            result = _attach_anchor(direct[:normalized_limit], seed_artist, seed_title)
            if not track_call_failed:
                _store_cache(cache_key, result, current_time)
            return result

        artist_payload = await _request(
            active_client,
            key,
            "artist.getsimilar",
            artist=seed_artist,
            limit=str(min(MAX_SIMILAR_ARTISTS, normalized_limit)),
        )
        artist_call_failed = not artist_payload
        related_artists = _parse_similar_artists(artist_payload, seed_artist)

        if direct and broaden:
            # Keep the direct track-level matches first (still the strongest evidence),
            # then top up with related-artist signals for real breadth.
            combined = _deduplicate(
                [*direct, *related_artists],
                excluded={_key(seed_artist, seed_title)},
                limit=normalized_limit,
            )
            result = _attach_anchor(combined, seed_artist, seed_title)
            if not (track_call_failed or artist_call_failed):
                _store_cache(cache_key, result, current_time)
            return result

        result = _attach_anchor(
            related_artists[:normalized_limit],
            seed_artist,
            seed_title,
        )
        if not (track_call_failed or artist_call_failed):
            _store_cache(cache_key, result, current_time)
        return result
    except (httpx.HTTPError, ValueError, TypeError) as error:
        LOGGER.info("Last.fm discovery unavailable: %s", error)
        return []
    finally:
        if owns_client:
            await active_client.aclose()


async def discover_from_anchors(
    anchors: list[dict[str, str]],
    *,
    limit: int = 40,
    max_anchors: int = MAX_PROMPT_ANCHORS,
) -> list[dict[str, str]]:
    """Skip prompt-anchor expansion; ReccoBeats now handles prompt creative evidence.

    Last.fm discovery remains enabled for explicit seed playlists through
    :func:`discover_for_seed`. Expanding AI-generated prompt anchors caused a second full
    playlist generation while adding broad collaborative signals after the creative guard
    had already validated the first draft.
    """
    _ = anchors, limit, max_anchors
    return []
