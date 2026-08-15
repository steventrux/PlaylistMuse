"""Resolve AI suggestions and search seeds in the YouTube Music catalogue.

Stable low-level helpers live in :mod:`backend.youtube_core`; request-aware matching and
metadata orchestration remain here so the public module and its test seams stay unchanged.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx

from backend import youtube_core as _core
from backend.metadata_runtime import (
    MetadataServiceUnavailableError,
    metadata_lookup_limit,
)
from backend.metadata_validation import (
    USER_AGENT as METADATA_USER_AGENT,
    ValidationResult,
    active_constraints,
    validate_candidate,
)
from backend.youtube_core import (
    DEFAULT_YOUTUBE_CACHE_TTL_SECONDS,
    DEFAULT_YOUTUBE_NEGATIVE_CACHE_TTL_SECONDS,
    LOGGER,
    MAX_METADATA_LOOKUP_ATTEMPTS,
    METADATA_VALIDATION_BATCH_SIZE,
    MIN_ARTIST_SCORE,
    MIN_COMBINED_SCORE,
    MIN_TITLE_SCORE,
    _CACHE_DIAGNOSTIC_KEY,
    _album_name,
    _artist_score,
    _artist_text,
    _budget_exceeded_result,
    _canonicalize_fallback_metadata,
    _decorate_resolved_track,
    _log_unresolved_candidate,
    _looks_like_collection,
    _metadata_fallback_candidates,
    _metadata_rejection,
    _metadata_retryable,
    _pair_diagnostic,
    _prefer_metadata_result,
    _resolution_failure_reason,
    _serialize_song,
    _set_resolution_diagnostic,
    _take_resolution_diagnostic,
    _temporarily_unavailable,
    _thread_client,
    _youtube_cache_connect,
    _youtube_resolution_concurrency,
    track_identity_key,
)
from backend.youtube_matching import (
    exclusion_reason as _contextual_exclusion_reason,
    title_score as _case_insensitive_title_score,
)

# Preserve the existing module-level helper surface without runtime patching.
DEFAULT_YOUTUBE_RESOLUTION_CONCURRENCY = _core.DEFAULT_YOUTUBE_RESOLUTION_CONCURRENCY
_client = _core._client
_metadata_artist_aliases = _core._metadata_artist_aliases
_metadata_title_aliases = _core._metadata_title_aliases
_search_songs = _core._search_songs
_strip_feature_suffix = _core._strip_feature_suffix
_thumbnail = _core._thumbnail
_youtube_cache_path = _core._youtube_cache_path
search_songs = _core.search_songs

YOUTUBE_CACHE_VERSION = "4"


def _youtube_cache_key(candidate: dict[str, str], exclusions: dict[str, bool]) -> str:
    flags = "".join(
        "1" if exclusions.get(name, True) else "0"
        for name in ("exclude_live", "exclude_covers", "exclude_remixes")
    )
    identity = track_identity_key(
        candidate.get("title", ""), candidate.get("artist", "")
    )
    return f"{YOUTUBE_CACHE_VERSION}|{identity}|{flags}"


def _read_youtube_cache_entry(
    candidate: dict[str, str],
    exclusions: dict[str, bool],
    *,
    path: Path | None = None,
) -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None]:
    try:
        with _youtube_cache_connect(path) as connection:
            row = connection.execute(
                "SELECT payload, expires_at FROM youtube_resolution_cache WHERE cache_key = ?",
                (_youtube_cache_key(candidate, exclusions),),
            ).fetchone()
            if not row or float(row["expires_at"]) <= time.time():
                return False, None, None
            payload = row["payload"]
            if not payload:
                return True, None, None
            decoded = json.loads(str(payload))
            if isinstance(decoded, dict) and _CACHE_DIAGNOSTIC_KEY in decoded:
                diagnostic = decoded.get(_CACHE_DIAGNOSTIC_KEY)
                if isinstance(diagnostic, dict) and "best_pair" not in diagnostic:
                    return False, None, None
                return True, None, diagnostic if isinstance(diagnostic, dict) else None
            return True, decoded if isinstance(decoded, dict) else None, None
    except (sqlite3.Error, ValueError, TypeError, json.JSONDecodeError):
        return False, None, None


def _read_youtube_cache(
    candidate: dict[str, str],
    exclusions: dict[str, bool],
    *,
    path: Path | None = None,
) -> tuple[bool, dict[str, Any] | None]:
    hit, track, _ = _read_youtube_cache_entry(
        candidate,
        exclusions,
        path=path,
    )
    return hit, track


def _write_youtube_cache(
    candidate: dict[str, str],
    exclusions: dict[str, bool],
    track: dict[str, Any] | None,
    *,
    diagnostic: dict[str, Any] | None = None,
    path: Path | None = None,
) -> None:
    ttl = (
        DEFAULT_YOUTUBE_CACHE_TTL_SECONDS
        if track is not None
        else DEFAULT_YOUTUBE_NEGATIVE_CACHE_TTL_SECONDS
    )
    payload: dict[str, Any] | None = track
    if track is None and diagnostic:
        payload = {_CACHE_DIAGNOSTIC_KEY: diagnostic}
    try:
        with _youtube_cache_connect(path) as connection:
            connection.execute(
                """
                INSERT INTO youtube_resolution_cache(cache_key, payload, expires_at)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                  payload = excluded.payload,
                  expires_at = excluded.expires_at
                """,
                (
                    _youtube_cache_key(candidate, exclusions),
                    json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                    time.time() + ttl,
                ),
            )
    except (sqlite3.Error, TypeError, ValueError):
        return


def _exclusion_reason(
    title: str,
    *,
    album: str = "",
    artists: str = "",
    candidate_title: str = "",
    candidate_artists: str = "",
    live: bool,
    covers: bool,
    remixes: bool,
) -> str | None:
    """Reject only variant markers added by the catalogue result."""
    return _contextual_exclusion_reason(
        title,
        album=album,
        artists=artists,
        candidate_title=candidate_title,
        candidate_artists=candidate_artists,
        live=live,
        covers=covers,
        remixes=remixes,
    )


def _is_excluded(
    title: str,
    *,
    album: str = "",
    artists: str = "",
    candidate_title: str = "",
    candidate_artists: str = "",
    live: bool,
    covers: bool,
    remixes: bool,
) -> bool:
    return _exclusion_reason(
        title,
        album=album,
        artists=artists,
        candidate_title=candidate_title,
        candidate_artists=candidate_artists,
        live=live,
        covers=covers,
        remixes=remixes,
    ) is not None


def _title_score(candidate_title: str, result_title: str) -> float:
    """Reward close titles case-insensitively and penalize noisy suffixes."""
    return _case_insensitive_title_score(candidate_title, result_title)


def _resolve_one(
    candidate: dict[str, str], exclusions: dict[str, bool]
) -> dict[str, Any] | None:
    _set_resolution_diagnostic(None)
    cache_hit, cached, cached_diagnostic = _read_youtube_cache_entry(
        candidate, exclusions
    )
    if cache_hit:
        if cached is not None:
            return _decorate_resolved_track(cached, candidate)
        _set_resolution_diagnostic(
            cached_diagnostic or {"reason": "cached_no_match"}
        )
        return None

    query = f"{candidate['artist']} {candidate['title']}"
    results = _thread_client().search(query, filter="songs", limit=12)
    best: tuple[float, dict[str, Any]] | None = None
    best_pair: dict[str, Any] | None = None
    best_pair_score = -1.0
    exclude_live = exclusions.get("exclude_live", True)
    exclude_covers = exclusions.get("exclude_covers", True)
    exclude_remixes = exclusions.get("exclude_remixes", True)
    stats: dict[str, int] = {"results": len(results), "usable_results": 0}
    best_title_score = 0.0
    best_artist_score = 0.0
    best_combined_score = 0.0

    for result in results:
        video_id = result.get("videoId")
        title = str(result.get("title", ""))
        artists = _artist_text(result)
        album = _album_name(result)
        if not video_id or not title or not artists:
            stats["unusable_result"] = stats.get("unusable_result", 0) + 1
            continue
        stats["usable_results"] += 1
        title_score = _title_score(candidate["title"], title)
        artist_score = _artist_score(candidate["artist"], artists)
        combined_score = title_score * 0.68 + artist_score * 0.32
        exclusion_reason = _exclusion_reason(
            title,
            album=album,
            artists=artists,
            candidate_title=candidate["title"],
            candidate_artists=candidate["artist"],
            live=exclude_live,
            covers=exclude_covers,
            remixes=exclude_remixes,
        )
        collection = _looks_like_collection(candidate["title"], title)
        if combined_score > best_pair_score:
            best_pair_score = combined_score
            best_pair = _pair_diagnostic(
                result,
                title=title,
                artists=artists,
                album=album,
                title_score=title_score,
                artist_score=artist_score,
                exclusion_reason=exclusion_reason,
                collection=collection,
            )
        if exclusion_reason:
            stats[exclusion_reason] = stats.get(exclusion_reason, 0) + 1
            continue
        if collection:
            stats["collection"] = stats.get("collection", 0) + 1
            continue

        best_title_score = max(best_title_score, title_score)
        best_artist_score = max(best_artist_score, artist_score)
        if title_score < MIN_TITLE_SCORE:
            stats["title_mismatch"] = stats.get("title_mismatch", 0) + 1
            continue
        if artist_score < MIN_ARTIST_SCORE:
            stats["artist_mismatch"] = stats.get("artist_mismatch", 0) + 1
            continue

        score = combined_score
        best_combined_score = max(best_combined_score, score)
        if best is None or score > best[0]:
            best = (score, result)

    if best is None:
        diagnostic = {
            "reason": _resolution_failure_reason(stats),
            "best_title_score": round(best_title_score, 1),
            "best_artist_score": round(best_artist_score, 1),
            "best_pair": best_pair,
            **stats,
        }
        _write_youtube_cache(
            candidate,
            exclusions,
            None,
            diagnostic=diagnostic,
        )
        _set_resolution_diagnostic(diagnostic)
        return None

    if best[0] < MIN_COMBINED_SCORE:
        diagnostic = {
            "reason": "combined_score_below_threshold",
            "best_title_score": round(best_title_score, 1),
            "best_artist_score": round(best_artist_score, 1),
            "best_combined_score": round(max(best_combined_score, best[0]), 1),
            "best_pair": best_pair,
            **stats,
        }
        _write_youtube_cache(
            candidate,
            exclusions,
            None,
            diagnostic=diagnostic,
        )
        _set_resolution_diagnostic(diagnostic)
        return None

    song = _serialize_song(best[1])
    if not song:
        diagnostic = {
            "reason": "serialization_failed",
            "best_pair": best_pair,
            **stats,
        }
        _write_youtube_cache(
            candidate,
            exclusions,
            None,
            diagnostic=diagnostic,
        )
        _set_resolution_diagnostic(diagnostic)
        return None
    song["match_score"] = round(best[0], 1)
    _write_youtube_cache(candidate, exclusions, song)
    return _decorate_resolved_track(song, candidate)


def _resolve_one_with_diagnostic(
    candidate: dict[str, str], exclusions: dict[str, bool]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    _set_resolution_diagnostic(None)
    track = _resolve_one(candidate, exclusions)
    return track, _take_resolution_diagnostic()


def _incremental_metadata_target(candidate_count: int) -> int | None:
    """Bound simple replenishment checks while preserving complex request semantics."""
    if candidate_count <= 0:
        return None

    from backend import generation_runtime as runtime
    from backend.policy_enforcement import _ACTIVE_POLICY, _REPLACEMENT_MODE

    if _REPLACEMENT_MODE.get():
        return None
    requested = runtime._REQUESTED_SESSION_COUNT.get()
    already_resolved = len(runtime._RESOLVED_SESSION_TRACKS.get())
    if requested <= 0 or already_resolved <= 0:
        return None
    missing = max(0, requested - already_resolved)
    if missing <= 0:
        return 0
    if runtime._ACTIVE_RESOLUTION_QUOTAS.get():
        return None
    if runtime._ACTIVE_EXACT_ARTIST_QUOTAS.get():
        return None
    policy = _ACTIVE_POLICY.get()
    if policy is not None and getattr(policy, "active", False):
        return None

    reserve = min(4, max(2, (missing + 2) // 3))
    target = min(candidate_count, missing + reserve)
    return target if target < candidate_count else None


async def _metadata_filter(
    candidates: list[dict[str, str]],
    *,
    max_valid: int | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    constraints = active_constraints()
    if not constraints.active:
        return list(candidates), []

    unique_candidates: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    for candidate in candidates:
        key = track_identity_key(
            candidate.get("title", ""),
            candidate.get("artist", ""),
        )
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        unique_candidates.append(candidate)

    accepted: list[dict[str, str]] = []
    rejected: list[dict[str, Any]] = []
    remaining_lookups = metadata_lookup_limit(
        len(unique_candidates) * MAX_METADATA_LOOKUP_ATTEMPTS
    )
    network_attempts = 0
    temporary_failures = 0
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(8.0),
        headers={
            "User-Agent": METADATA_USER_AGENT,
            "Accept": "application/json",
        },
    ) as client:

        async def evaluate(candidate: dict[str, str]) -> ValidationResult:
            nonlocal remaining_lookups, network_attempts, temporary_failures
            # Deliberately no cache short-circuit here: validate_candidate() already
            # caches internally (via lookup_track_metadata()), and it re-derives whether
            # a historical probe or artist-origin enrichment is still needed for the
            # constraints active in *this* request. A cache-key of artist+title alone
            # (shared across all requests for up to 90 days) means a naive fast path here
            # would "lock in" whatever fields the first-ever request happened to need,
            # silently starving later requests that need e.g. artist_country of the
            # enrichment they require.
            if remaining_lookups <= 0:
                return _budget_exceeded_result(candidate)
            remaining_lookups -= 1
            network_attempts += 1
            result = await validate_candidate(
                candidate,
                constraints,
                client=client,
            )
            if _temporarily_unavailable(result):
                temporary_failures += 1
            return result

        async def resolve_one(
            candidate: dict[str, str],
        ) -> tuple[dict[str, str] | None, dict[str, Any] | None]:
            canonical_artist = str(candidate.get("artist", "")).strip()
            canonical_title = str(candidate.get("title", "")).strip()
            result = await evaluate(candidate)
            if _metadata_retryable(result, constraints):
                for alternative_candidate in _metadata_fallback_candidates(candidate):
                    alternative = await evaluate(alternative_candidate)
                    if _prefer_metadata_result(result, alternative):
                        result = _canonicalize_fallback_metadata(
                            alternative,
                            canonical_artist=canonical_artist,
                            canonical_title=canonical_title,
                            alias_artist=str(alternative_candidate.get("artist", "")),
                            alias_title=str(alternative_candidate.get("title", "")),
                        )
                    if result.status == "valid":
                        break

            if result.status == "valid":
                copy = dict(candidate)
                copy["metadata_validation"] = asdict(result.metadata)  # type: ignore[assignment]
                return copy, None
            rejection = _metadata_rejection(candidate, result)
            if _temporarily_unavailable(result):
                rejection["unresolved_reason"] = "metadata_service_unavailable"
            return None, rejection

        # Dispatched in small concurrent batches rather than one candidate at a time:
        # MusicBrainz calls are paced through a single process-wide scheduler
        # (musicbrainz_client.rate_limited_get), so sequential awaiting wastes each
        # candidate's full response latency before the next candidate's slot is even
        # requested. Batching (instead of one all-at-once gather()) preserves the
        # early-stop-once-max_valid-is-reached check between batches, so it can't
        # overshoot by more than one batch's worth of already-in-flight lookups.
        index = 0
        while index < len(unique_candidates):
            if max_valid is not None and len(accepted) >= max_valid:
                deferred = unique_candidates[index:]
                rejected.extend(
                    {
                        **item,
                        "unresolved_reason": "metadata_deferred_after_target",
                    }
                    for item in deferred
                )
                LOGGER.info(
                    "catalogue_metadata outcome=stopped_early target=%s accepted=%s "
                    "deferred=%s candidates=%s",
                    max_valid,
                    len(accepted),
                    len(deferred),
                    len(unique_candidates),
                )
                break

            batch = unique_candidates[index : index + METADATA_VALIDATION_BATCH_SIZE]
            index += len(batch)
            batch_results = await asyncio.gather(
                *(resolve_one(candidate) for candidate in batch)
            )
            for accepted_copy, rejection in batch_results:
                if accepted_copy is not None:
                    accepted.append(accepted_copy)
                else:
                    rejected.append(rejection)

    if network_attempts > 0 and temporary_failures == network_attempts:
        raise MetadataServiceUnavailableError(
            "MusicBrainz metadata verification is temporarily unavailable."
        )
    return accepted, rejected


async def resolve_candidates(
    candidates: list[dict[str, str]], exclusions: dict[str, bool]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve on YouTube Music first, then validate the canonical catalogue identity."""
    unique_candidates: list[dict[str, str]] = []
    seen_candidate_keys: set[str] = set()
    for candidate in candidates:
        candidate_key = track_identity_key(candidate["title"], candidate["artist"])
        if not candidate_key or candidate_key in seen_candidate_keys:
            continue
        seen_candidate_keys.add(candidate_key)
        unique_candidates.append(candidate)

    semaphore = asyncio.Semaphore(_youtube_resolution_concurrency())

    async def resolve(
        candidate: dict[str, str],
    ) -> tuple[
        dict[str, str],
        dict[str, Any] | None,
        dict[str, Any] | None,
    ]:
        async with semaphore:
            track, diagnostic = await asyncio.to_thread(
                _resolve_one_with_diagnostic,
                candidate,
                exclusions,
            )
            return candidate, track, diagnostic

    resolution_results = await asyncio.gather(
        *(resolve(candidate) for candidate in unique_candidates)
    )

    unresolved: list[dict[str, Any]] = []
    catalogue_matches: dict[str, tuple[dict[str, str], dict[str, Any]]] = {}
    canonical_candidates: list[dict[str, str]] = []
    for candidate, track, diagnostic in resolution_results:
        if not track:
            rejection = {
                **candidate,
                "unresolved_reason": "youtube_resolution",
                "youtube_resolution": diagnostic or {"reason": "unknown"},
            }
            unresolved.append(rejection)
            _log_unresolved_candidate(rejection)
            continue
        canonical_key = track_identity_key(track["title"], track["artists"])
        if not canonical_key or canonical_key in catalogue_matches:
            continue
        catalogue_matches[canonical_key] = (candidate, track)
        canonical_candidates.append(
            {
                **candidate,
                "requested_artist": str(candidate.get("artist", "")),
                "requested_title": str(candidate.get("title", "")),
                "artist": str(track["artists"]),
                "title": str(track["title"]),
            }
        )

    metadata_target = _incremental_metadata_target(len(canonical_candidates))
    if metadata_target is None:
        validated_candidates, metadata_rejected = await _metadata_filter(
            canonical_candidates
        )
    else:
        validated_candidates, metadata_rejected = await _metadata_filter(
            canonical_candidates,
            max_valid=metadata_target,
        )
    accepted_by_key = {
        track_identity_key(candidate["title"], candidate["artist"]): candidate
        for candidate in validated_candidates
    }
    rejected_by_key = {
        track_identity_key(candidate["title"], candidate["artist"]): candidate
        for candidate in metadata_rejected
    }

    resolved: list[dict[str, Any]] = []
    seen_video_ids: set[str] = set()
    seen_track_keys: set[str] = set()
    for canonical_key, (candidate, track) in catalogue_matches.items():
        accepted = accepted_by_key.get(canonical_key)
        if accepted is None:
            rejection = rejected_by_key.get(canonical_key)
            if rejection is not None:
                unresolved_item = {
                    **candidate,
                    "unresolved_reason": rejection.get(
                        "unresolved_reason", "metadata_validation"
                    ),
                    "metadata_validation": rejection.get(
                        "metadata_validation", {}
                    ),
                    "resolved_catalogue": {
                        "title": track.get("title"),
                        "artists": track.get("artists"),
                        "video_id": track.get("video_id"),
                    },
                }
                unresolved.append(unresolved_item)
                _log_unresolved_candidate(unresolved_item)
            continue

        track_key = track_identity_key(track["title"], track["artists"])
        if track["video_id"] in seen_video_ids or track_key in seen_track_keys:
            continue
        metadata = accepted.get("metadata_validation")
        if isinstance(metadata, dict):
            track["metadata_validation"] = metadata
        seen_video_ids.add(track["video_id"])
        seen_track_keys.add(track_key)
        resolved.append(track)

    return resolved, unresolved
