"""Last.fm discovery signals used as evidence by the playlist AI."""

from __future__ import annotations

import asyncio
import logging
import math
import re
import unicodedata
from typing import Any

import httpx

from backend.lastfm import API_ROOT, USER_AGENT, _environment_timeout
from backend.lastfm_settings import lastfm_api_key

LOGGER = logging.getLogger(__name__)
MAX_CONTEXT_TRACKS = 60
MAX_PROMPT_ANCHORS = 3


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value).casefold())
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[a-z0-9]+", without_marks))


def _key(artist: str, title: str) -> tuple[str, str]:
    return (_normalize(artist), _normalize(title))


def _artist_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name", "")).strip()
    return str(value or "").strip()


def _candidate(
    artist: str,
    title: str,
    *,
    strategy: str,
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
        "lastfm_strategy": strategy,
        "lastfm_match": str(match or "").strip(),
    }


def _deduplicate(
    candidates: list[dict[str, str]],
    *,
    excluded: set[tuple[str, str]] | None = None,
    limit: int = MAX_CONTEXT_TRACKS,
) -> list[dict[str, str]]:
    unique: list[dict[str, str]] = []
    seen = set(excluded or set())
    for candidate in candidates:
        identity = _key(candidate.get("artist", ""), candidate.get("title", ""))
        if not all(identity) or identity in seen:
            continue
        seen.add(identity)
        unique.append(candidate)
        if len(unique) >= max(1, min(MAX_CONTEXT_TRACKS, limit)):
            break
    return unique


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
    candidates: list[dict[str, str]] = []
    for item in raw_tracks:
        if not isinstance(item, dict):
            continue
        candidate = _candidate(
            _artist_name(item.get("artist")),
            str(item.get("name", "")),
            strategy="similar_track",
            match=str(item.get("match", "")),
        )
        if candidate and _key(candidate["artist"], candidate["title"]) != seed_key:
            candidates.append(candidate)
    return _deduplicate(candidates, excluded={seed_key})


def _parse_similar_artists(payload: dict[str, Any]) -> list[tuple[str, str]]:
    raw_artists = payload.get("similarartists", {}).get("artist", [])
    if isinstance(raw_artists, dict):
        raw_artists = [raw_artists]
    if not isinstance(raw_artists, list):
        return []

    artists: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in raw_artists:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        normalized = _normalize(name)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        artists.append((name, str(item.get("match", "")).strip()))
    return artists


def _parse_top_tracks(
    payload: dict[str, Any],
    fallback_artist: str,
    artist_match: str,
    per_artist: int,
) -> list[dict[str, str]]:
    raw_tracks = payload.get("toptracks", {}).get("track", [])
    if isinstance(raw_tracks, dict):
        raw_tracks = [raw_tracks]
    if not isinstance(raw_tracks, list):
        return []

    candidates: list[dict[str, str]] = []
    for item in raw_tracks[: max(1, per_artist)]:
        if not isinstance(item, dict):
            continue
        candidate = _candidate(
            _artist_name(item.get("artist")) or fallback_artist,
            str(item.get("name", "")),
            strategy="similar_artist",
            match=artist_match,
        )
        if candidate:
            candidates.append(candidate)
    return candidates


async def discover_for_seed(
    artist: str,
    title: str,
    *,
    limit: int = 40,
    api_key: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, str]]:
    """Return collaborative track evidence, falling back to similar artists."""
    seed_artist = " ".join(str(artist).split())
    seed_title = " ".join(str(title).split())
    key = (api_key if api_key is not None else lastfm_api_key()).strip()
    normalized_limit = max(1, min(MAX_CONTEXT_TRACKS, int(limit)))
    if not key or not seed_artist or not seed_title:
        return []

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
        direct = _parse_similar_tracks(similar_payload, seed_artist, seed_title)
        if direct:
            return direct[:normalized_limit]

        artist_payload = await _request(
            active_client,
            key,
            "artist.getsimilar",
            artist=seed_artist,
            limit=str(min(10, max(4, math.ceil(normalized_limit / 2)))),
        )
        similar_artists = _parse_similar_artists(artist_payload)
        if not similar_artists:
            return []

        per_artist = 2
        artist_limit = min(len(similar_artists), math.ceil(normalized_limit / per_artist))

        async def top_tracks(name: str, match: str) -> list[dict[str, str]]:
            payload = await _request(
                active_client,
                key,
                "artist.gettoptracks",
                artist=name,
                limit=str(per_artist),
            )
            return _parse_top_tracks(payload, name, match, per_artist)

        groups = await asyncio.gather(
            *(top_tracks(name, match) for name, match in similar_artists[:artist_limit]),
            return_exceptions=True,
        )
        fallback: list[dict[str, str]] = []
        for group in groups:
            if isinstance(group, Exception):
                LOGGER.info("Last.fm similar-artist top tracks unavailable: %s", group)
                continue
            fallback.extend(group)
        return _deduplicate(
            fallback,
            excluded={_key(seed_artist, seed_title)},
            limit=normalized_limit,
        )
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
    """Use AI first-pass songs as Last.fm anchors for free-text prompts."""
    key = lastfm_api_key().strip()
    normalized_limit = max(1, min(MAX_CONTEXT_TRACKS, int(limit)))
    if not key:
        return []

    selected: list[dict[str, str]] = []
    seen_anchors: set[tuple[str, str]] = set()
    for anchor in anchors:
        artist = str(anchor.get("artist", "")).strip()
        title = str(anchor.get("title", "")).strip()
        identity = _key(artist, title)
        if not all(identity) or identity in seen_anchors:
            continue
        seen_anchors.add(identity)
        selected.append({"artist": artist, "title": title})
        if len(selected) >= max(1, min(MAX_PROMPT_ANCHORS, max_anchors)):
            break
    if not selected:
        return []

    per_anchor = max(6, math.ceil(normalized_limit / len(selected)))
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(_environment_timeout()),
        headers={"User-Agent": USER_AGENT},
    ) as client:
        groups = await asyncio.gather(
            *(
                discover_for_seed(
                    anchor["artist"],
                    anchor["title"],
                    limit=per_anchor,
                    api_key=key,
                    client=client,
                )
                for anchor in selected
            ),
            return_exceptions=True,
        )

    candidates: list[dict[str, str]] = []
    excluded = {_key(anchor["artist"], anchor["title"]) for anchor in selected}
    for group in groups:
        if isinstance(group, Exception):
            LOGGER.info("Last.fm prompt-anchor discovery unavailable: %s", group)
            continue
        candidates.extend(group)
    return _deduplicate(candidates, excluded=excluded, limit=normalized_limit)
