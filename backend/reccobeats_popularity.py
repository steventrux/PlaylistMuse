"""Popularity-aware helpers for ReccoBeats discovery."""

from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar
from typing import Any

import httpx

from backend.reccobeats_features import (
    API_ROOT,
    DEFAULT_TIMEOUT_SECONDS,
    _content,
    _resolve_track_candidate,
)
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


def _track_identity(track: dict[str, Any]) -> tuple[str, str]:
    artist = str(track.get("artist") or track.get("artists") or "").strip()
    title = str(track.get("title") or "").strip()
    return normalize_identity(artist), normalize_identity(title)


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
        updated_ids[track_id] = score
    if all(identity):
        updated_identities[identity] = score
    _POPULARITY_BY_ID.set(updated_ids)
    _POPULARITY_BY_IDENTITY.set(updated_identities)


def _cached_score(track: dict[str, Any]) -> int | None:
    by_id, by_identity = _cache_maps()
    track_id = str(track.get("reccobeats_id", "")).strip()
    if track_id and track_id in by_id:
        return by_id[track_id]
    return by_identity.get(_track_identity(track))


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
        score = _popularity(copy.get("popularity"))
        if score is not None:
            _remember_score(copy, score)
        else:
            score = _cached_score(copy)
            if score is not None:
                copy["popularity"] = score
        enriched.append(copy)
    return enriched


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

    async def fetch_batch(
        client: httpx.AsyncClient,
        batch: list[str],
    ) -> list[dict[str, Any]]:
        response = await client.get(
            f"{API_ROOT}/track",
            params={"ids": ",".join(batch)},
        )
        response.raise_for_status()
        return _content(response.json())

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(DEFAULT_TIMEOUT_SECONDS),
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        ) as client:
            tasks = [asyncio.create_task(fetch_batch(client, batch)) for batch in batches]
            done, pending = await asyncio.wait(tasks, timeout=TIMEOUT_SECONDS)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        details: list[dict[str, Any]] = []
        failed = len(pending)
        for task in done:
            try:
                details.extend(task.result())
            except Exception:  # noqa: BLE001 - partial optional enrichment is useful.
                failed += 1
        if failed:
            LOGGER.info(
                "reccobeats_popularity_enrichment batches=%s failed=%s preserved_cache=%s",
                len(batches),
                failed,
                len(_POPULARITY_BY_ID.get() or {}),
            )

        for item in details:
            track_id = str(item.get("id", "")).strip()
            score = _popularity(item.get("popularity"))
            if track_id and score is not None:
                _remember_score(item, score, reccobeats_id=track_id)

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
        artist = str(track.get("artist") or track.get("artists") or "").strip()
        title = str(track.get("title") or "").strip()
        identity = _track_identity(track)
        candidate = await _resolve_track_candidate(client, artist, title)
        score = _popularity(candidate.get("popularity")) if candidate else None
        track_id = str((candidate or {}).get("id", "")).strip()
        return identity, score, track_id

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(DEFAULT_TIMEOUT_SECONDS),
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        ) as client:
            tasks = [asyncio.create_task(resolve(client, track)) for track in missing]
            done, pending = await asyncio.wait(tasks, timeout=TIMEOUT_SECONDS)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        for task in done:
            try:
                identity, score, track_id = task.result()
            except Exception:  # noqa: BLE001 - optional enrichment is fail-open.
                continue
            if all(identity) and score is not None:
                scores[identity] = score
                _remember_score(
                    {"artist": identity[0], "title": identity[1]},
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
