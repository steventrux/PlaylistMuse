"""Popularity-aware helpers for ReccoBeats discovery."""

from __future__ import annotations

import asyncio
import logging
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

TIMEOUT_SECONDS = 5.0
TRACK_DETAIL_BATCH_SIZE = 30
LOGGER = logging.getLogger(__name__)


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


async def enrich_recommendation_popularity(
    candidates: list[dict[str, Any]],
    *,
    preference: str = "neutral",
) -> list[dict[str, Any]]:
    """Attach Track.popularity to recommendation identities when Recco exposes it."""
    if not candidates:
        return []

    ids = list(
        dict.fromkeys(
            str(candidate.get("reccobeats_id", "")).strip()
            for candidate in candidates
            if str(candidate.get("reccobeats_id", "")).strip()
        )
    )
    if not ids:
        return rank_by_popularity(candidates, preference)

    batches = [
        ids[start : start + TRACK_DETAIL_BATCH_SIZE]
        for start in range(0, len(ids), TRACK_DETAIL_BATCH_SIZE)
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
            tasks = [
                asyncio.create_task(fetch_batch(client, batch))
                for batch in batches
            ]
            done, pending = await asyncio.wait(tasks, timeout=TIMEOUT_SECONDS)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        details: list[dict[str, Any]] = []
        failed = 0
        for task in done:
            try:
                details.extend(task.result())
            except Exception:  # noqa: BLE001 - partial optional enrichment is useful.
                failed += 1
        if failed:
            LOGGER.info(
                "ReccoBeats popularity enrichment partial batches=%s failed=%s",
                len(batches),
                failed,
            )

        scores = {
            str(item.get("id", "")).strip(): score
            for item in details
            if str(item.get("id", "")).strip()
            and (score := _popularity(item.get("popularity"))) is not None
        }
        enriched: list[dict[str, Any]] = []
        for candidate in candidates:
            copy = dict(candidate)
            score = scores.get(str(copy.get("reccobeats_id", "")).strip())
            if score is not None:
                copy["popularity"] = score
            enriched.append(copy)
        return rank_by_popularity(enriched, preference)
    except (httpx.HTTPError, ValueError, TypeError) as error:
        LOGGER.info(
            "ReccoBeats popularity enrichment unavailable candidates=%s error=%s",
            len(candidates),
            type(error).__name__,
        )
        return rank_by_popularity(candidates, preference)


async def popularity_for_tracks(
    tracks: list[dict[str, Any]],
) -> dict[tuple[str, str], int]:
    """Fetch Recco popularity for LLM identities only when the request needs it."""
    if not tracks:
        return {}

    async def resolve(
        client: httpx.AsyncClient,
        track: dict[str, Any],
    ) -> tuple[tuple[str, str], int | None]:
        artist = str(track.get("artist") or track.get("artists") or "").strip()
        title = str(track.get("title") or "").strip()
        identity = _track_identity(track)
        candidate = await _resolve_track_candidate(client, artist, title)
        score = _popularity(candidate.get("popularity")) if candidate else None
        return identity, score

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(DEFAULT_TIMEOUT_SECONDS),
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        ) as client:
            tasks = [asyncio.create_task(resolve(client, track)) for track in tracks]
            done, pending = await asyncio.wait(tasks, timeout=TIMEOUT_SECONDS)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
        scores: dict[tuple[str, str], int] = {}
        for task in done:
            try:
                identity, score = task.result()
            except Exception:  # noqa: BLE001 - optional enrichment is fail-open.
                continue
            if all(identity) and score is not None:
                scores[identity] = score
        return scores
    except (httpx.HTTPError, ValueError, TypeError):
        return {}


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
        result.append(copy)
    return result
