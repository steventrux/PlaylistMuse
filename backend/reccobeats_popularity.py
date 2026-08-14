"""Popularity-aware helpers for ReccoBeats discovery."""

from __future__ import annotations

import asyncio
import logging
import time
from contextvars import ContextVar
from typing import Any

import httpx

from backend.reccobeats_features import (
    DEFAULT_TIMEOUT_SECONDS,
    SEARCH_SIZE,
    _content,
    _resolve_track_candidate,
    _strict_track_match,
)
from backend.reccobeats_http import request_json
from backend.text_normalization import normalize_identity
from backend.version import USER_AGENT

TIMEOUT_SECONDS = 8.0
TRACK_DETAIL_BATCH_SIZE = 30
LOGGER = logging.getLogger("playlistmuse.performance")

_POPULARITY_BY_ID: ContextVar[dict[str, int] | None] = ContextVar(
    "playlistmuse_recco_popularity_by_id",
    default=None,
)
_POPULARITY_BY_IDENTITY: ContextVar[dict[tuple[str, str], int] | None] = ContextVar(
    "playlistmuse_recco_popularity_by_identity",
    default=None,
)


def _popularity(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _artist_text(track: dict[str, Any]) -> str:
    artist = track.get("artist")
    if artist:
        return str(artist).strip()
    raw = track.get("artists")
    if isinstance(raw, dict):
        raw = [raw]
    if isinstance(raw, list):
        names = [
            str(item.get("name", "")).strip()
            for item in raw
            if isinstance(item, dict) and str(item.get("name", "")).strip()
        ]
        return ", ".join(names)
    return str(raw or "").strip()


def _title_text(track: dict[str, Any]) -> str:
    return str(
        track.get("title")
        or track.get("trackTitle")
        or track.get("name")
        or ""
    ).strip()


def _track_identity(track: dict[str, Any]) -> tuple[str, str]:
    return normalize_identity(_artist_text(track)), normalize_identity(_title_text(track))


def _cache_maps() -> tuple[dict[str, int], dict[tuple[str, str], int]]:
    by_id = _POPULARITY_BY_ID.get()
    by_identity = _POPULARITY_BY_IDENTITY.get()
    if by_id is None:
        by_id = {}
        _POPULARITY_BY_ID.set(by_id)
    if by_identity is None:
        by_identity = {}
        _POPULARITY_BY_IDENTITY.set(by_identity)
    return by_id, by_identity


def reset_request_popularity_cache() -> None:
    """Start a fresh score cache for one generation request."""
    _POPULARITY_BY_ID.set({})
    _POPULARITY_BY_IDENTITY.set({})


def _remember_score(
    track: dict[str, Any],
    score: int | None,
    *,
    reccobeats_id: str = "",
) -> None:
    if score is None:
        return
    by_id, by_identity = _cache_maps()
    updated_ids = dict(by_id)
    updated_identities = dict(by_identity)
    track_id = reccobeats_id or str(track.get("reccobeats_id", "")).strip()
    identity = _track_identity(track)
    if track_id:
        updated_ids[track_id] = max(score, updated_ids.get(track_id, score))
    if all(identity):
        updated_identities[identity] = max(
            score,
            updated_identities.get(identity, score),
        )
    _POPULARITY_BY_ID.set(updated_ids)
    _POPULARITY_BY_IDENTITY.set(updated_identities)


def _cached_score(track: dict[str, Any]) -> int | None:
    by_id, by_identity = _cache_maps()
    track_id = str(track.get("reccobeats_id", "")).strip()
    values: list[int] = []
    if track_id and track_id in by_id:
        values.append(by_id[track_id])
    identity_score = by_identity.get(_track_identity(track))
    if identity_score is not None:
        values.append(identity_score)
    return max(values) if values else None


def rank_by_popularity(
    candidates: list[dict[str, Any]],
    preference: str,
) -> list[dict[str, Any]]:
    """Rank known Recco popularity values relatively; unknown values stay neutral."""
    normalized = str(preference).strip().casefold()
    copied = [dict(candidate) for candidate in candidates]
    if normalized not in {"popular", "less_known"}:
        return copied

    def key(candidate: dict[str, Any]) -> tuple[int, int]:
        score = _popularity(candidate.get("popularity"))
        if score is None:
            return 1, 0
        return 0, -score if normalized == "popular" else score

    return sorted(copied, key=key)


def _apply_cached_scores(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for candidate in candidates:
        copy = dict(candidate)
        supplied = _popularity(copy.get("popularity"))
        if supplied is not None:
            _remember_score(copy, supplied)
        cached = _cached_score(copy)
        if cached is not None and (supplied is None or cached > supplied):
            copy["popularity"] = cached
        enriched.append(copy)
    return enriched


def _remember_detail_scores(details: list[dict[str, Any]]) -> None:
    """Keep the strongest score when Recco returns duplicate rows for one recording."""
    max_by_isrc: dict[str, int] = {}
    for item in details:
        isrc = str(item.get("isrc", "")).strip()
        score = _popularity(item.get("popularity"))
        if isrc and score is not None:
            max_by_isrc[isrc] = max(score, max_by_isrc.get(isrc, score))

    for item in details:
        track_id = str(item.get("id", "")).strip()
        score = _popularity(item.get("popularity"))
        isrc = str(item.get("isrc", "")).strip()
        if isrc and isrc in max_by_isrc:
            score = max_by_isrc[isrc]
        if track_id and score is not None:
            _remember_score(item, score, reccobeats_id=track_id)


async def enrich_recommendation_popularity(
    candidates: list[dict[str, Any]],
    *,
    preference: str = "neutral",
) -> list[dict[str, Any]]:
    """Attach Track.popularity while preserving request-scoped scores across retries."""
    if not candidates:
        return []

    prepared = _apply_cached_scores(candidates)
    by_id, _ = _cache_maps()
    ids = list(
        dict.fromkeys(
            str(candidate.get("reccobeats_id", "")).strip()
            for candidate in prepared
            if str(candidate.get("reccobeats_id", "")).strip()
        )
    )
    missing_ids = [track_id for track_id in ids if track_id not in by_id]
    LOGGER.info(
        "reccobeats_popularity_cache mode=details candidates=%s hits=%s misses=%s",
        len(prepared),
        len(ids) - len(missing_ids),
        len(missing_ids),
    )
    if not missing_ids:
        return rank_by_popularity(_apply_cached_scores(prepared), preference)

    batches = [
        missing_ids[start : start + TRACK_DETAIL_BATCH_SIZE]
        for start in range(0, len(missing_ids), TRACK_DETAIL_BATCH_SIZE)
    ]

    try:
        details: list[dict[str, Any]] = []
        failed = 0
        deadline = time.monotonic() + TIMEOUT_SECONDS
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(DEFAULT_TIMEOUT_SECONDS),
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        ) as client:
            for batch in batches:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    failed += 1
                    break
                try:
                    payload = await asyncio.wait_for(
                        request_json(
                            client,
                            "/track",
                            params={"ids": ",".join(batch)},
                        ),
                        timeout=remaining,
                    )
                    details.extend(_content(payload))
                except (asyncio.TimeoutError, httpx.HTTPError, ValueError, TypeError):
                    failed += 1
                    break

        if failed:
            LOGGER.info(
                "reccobeats_popularity_enrichment batches=%s failed=%s preserved_cache=%s",
                len(batches),
                failed,
                len(_POPULARITY_BY_ID.get() or {}),
            )

        _remember_detail_scores(details)
        enriched = _apply_cached_scores(prepared)
        return rank_by_popularity(enriched, preference)
    except (httpx.HTTPError, ValueError, TypeError) as error:
        LOGGER.info(
            "reccobeats_popularity_enrichment unavailable candidates=%s error=%s preserved_cache=%s",
            len(candidates),
            type(error).__name__,
            len(_POPULARITY_BY_ID.get() or {}),
        )
        return rank_by_popularity(_apply_cached_scores(prepared), preference)


async def _max_exact_search_match(
    client: httpx.AsyncClient,
    artist: str,
    title: str,
) -> dict[str, Any] | None:
    """Resolve one identity while collapsing duplicate exact Recco rows to the strongest score."""
    queries = (title, f"{artist} {title}")
    seen: set[str] = set()
    for query in queries:
        key = normalize_identity(query)
        if not key or key in seen:
            continue
        seen.add(key)
        payload = await request_json(
            client,
            "/track/search",
            params={"searchText": query, "size": SEARCH_SIZE, "page": 0},
        )
        matches = [
            item
            for item in _content(payload)
            if _strict_track_match(item, artist=artist, title=title)
        ]
        if matches:
            return max(
                matches,
                key=lambda item: _popularity(item.get("popularity"))
                if _popularity(item.get("popularity")) is not None
                else -1,
            )
    return None


async def popularity_for_tracks(
    tracks: list[dict[str, Any]],
) -> dict[tuple[str, str], int]:
    """Fetch only uncached Recco popularity for free-form LLM identities."""
    if not tracks:
        return {}

    _, by_identity = _cache_maps()
    scores: dict[tuple[str, str], int] = {}
    missing: list[dict[str, Any]] = []
    for track in tracks:
        identity = _track_identity(track)
        cached = by_identity.get(identity)
        if cached is not None:
            scores[identity] = cached
        else:
            missing.append(track)

    LOGGER.info(
        "reccobeats_popularity_cache mode=identity tracks=%s hits=%s misses=%s",
        len(tracks),
        len(tracks) - len(missing),
        len(missing),
    )
    if not missing:
        return scores

    async def resolve(
        client: httpx.AsyncClient,
        track: dict[str, Any],
    ) -> tuple[tuple[str, str], int | None, str]:
        artist = _artist_text(track)
        title = _title_text(track)
        identity = _track_identity(track)
        candidate = await _max_exact_search_match(client, artist, title)
        if candidate is None:
            candidate = await _resolve_track_candidate(client, artist, title)
        score = _popularity(candidate.get("popularity")) if candidate else None
        track_id = str((candidate or {}).get("id", "")).strip()
        return identity, score, track_id

    try:
        deadline = time.monotonic() + TIMEOUT_SECONDS
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(DEFAULT_TIMEOUT_SECONDS),
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        ) as client:
            for track in missing:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    identity, score, track_id = await asyncio.wait_for(
                        resolve(client, track),
                        timeout=remaining,
                    )
                except (asyncio.TimeoutError, httpx.HTTPError, ValueError, TypeError):
                    break
                if all(identity) and score is not None:
                    existing = scores.get(identity)
                    scores[identity] = max(score, existing if existing is not None else score)
                    _remember_score(
                        {"artist": _artist_text(track), "title": _title_text(track)},
                        score,
                        reccobeats_id=track_id,
                    )
        return scores
    except (httpx.HTTPError, ValueError, TypeError):
        return scores


def rank_tracks_by_popularity(
    tracks: list[dict[str, Any]],
    scores: dict[tuple[str, str], int],
    preference: str,
) -> list[dict[str, Any]]:
    """Rank LLM candidates by relative Recco popularity while preserving unknowns."""
    normalized = str(preference).strip().casefold()
    copied = [dict(track) for track in tracks]
    if normalized not in {"popular", "less_known"}:
        return copied

    def key(track: dict[str, Any]) -> tuple[int, int]:
        score = scores.get(_track_identity(track))
        if score is None:
            return 1, 0
        return 0, -score if normalized == "popular" else score

    return sorted(copied, key=key)


def canonicalize_reccobeats_matches(
    tracks: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep exact Recco identities while retaining LLM descriptions and reasons."""
    by_identity = {
        _track_identity(candidate): candidate
        for candidate in candidates
        if all(_track_identity(candidate))
    }
    result: list[dict[str, Any]] = []
    for track in tracks:
        copy = dict(track)
        candidate = by_identity.get(_track_identity(copy))
        if candidate is not None:
            copy["artist"] = str(candidate.get("artist", copy.get("artist", "")))
            copy["title"] = str(candidate.get("title", copy.get("title", "")))
            copy["source"] = "reccobeats"
            reccobeats_id = str(candidate.get("reccobeats_id", "")).strip()
            if reccobeats_id:
                copy["reccobeats_id"] = reccobeats_id
            popularity = _popularity(candidate.get("popularity"))
            if popularity is not None:
                copy["popularity"] = popularity
                _remember_score(copy, popularity)
        result.append(copy)
    return result
