"""Resolve AI suggestions and search seeds in the YouTube Music catalogue."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import threading
import time
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from rapidfuzz import fuzz
from ytmusicapi import YTMusic

from backend.metadata_validation import (
    USER_AGENT as METADATA_USER_AGENT,
    TrackMetadata,
    ValidationResult,
    _read_cache,
    active_constraints,
    validate_candidate,
    validate_metadata,
)
from backend.metadata_runtime import (
    MetadataServiceUnavailableError,
    metadata_lookup_limit,
)
from backend.text_normalization import normalize_identity as _normalize_identity

LOGGER = logging.getLogger("playlistmuse.performance")
_TITLE_TOKEN_RE = re.compile(r"[a-z0-9]+")
_LIVE_RE = re.compile(r"\b(live|concert|session)\b")
_REMIX_RE = re.compile(r"\b(remix|mix|edit|mashup)\b")
_COVER_RE = re.compile(r"\b(cover|tribute|karaoke)\b")
_ARTIST_SPLIT_RE = re.compile(
    r"\s*(?:,|&|×|\bx\b|\bfeat\.?\b|\bfeaturing\b|\bwith\b)\s*",
    re.IGNORECASE,
)
_COLLECTION_TERMS = (
    "medley",
    "full album",
    "greatest hits",
    "best of",
    "compilation",
    "complete album",
)
MIN_TITLE_SCORE = 70.0
MIN_ARTIST_SCORE = 75.0
MIN_COMBINED_SCORE = 72.0
DEFAULT_YOUTUBE_RESOLUTION_CONCURRENCY = 4
DEFAULT_YOUTUBE_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60
DEFAULT_YOUTUBE_NEGATIVE_CACHE_TTL_SECONDS = 24 * 60 * 60
YOUTUBE_CACHE_VERSION = "2"
MAX_METADATA_ARTIST_ATTEMPTS = 3
_CACHE_DIAGNOSTIC_KEY = "_playlistmuse_unresolved"
_THREAD_LOCAL = threading.local()


@lru_cache(maxsize=1)
def _client() -> YTMusic:
    """Return the shared client used by single-threaded catalogue searches."""
    return YTMusic()


def _thread_client() -> YTMusic:
    """Return one YouTube Music client per worker thread."""
    client = getattr(_THREAD_LOCAL, "client", None)
    if client is None:
        client = YTMusic()
        _THREAD_LOCAL.client = client
    return client


def _artist_text(result: dict[str, Any]) -> str:
    return ", ".join(str(item.get("name", "")) for item in result.get("artists", []))


def _album_name(result: dict[str, Any]) -> str:
    album = result.get("album") or {}
    if isinstance(album, dict):
        return str(album.get("name", "")).strip()
    return str(album).strip()


def _thumbnail(result: dict[str, Any]) -> str | None:
    thumbnails = result.get("thumbnails") or []
    return thumbnails[-1].get("url") if thumbnails else None


def track_identity_key(title: str, artists: str) -> str:
    """Return a stable song identity independent from its YouTube video ID."""
    return f"{_normalize_identity(artists)}::{_normalize_identity(title)}"


def _serialize_song(result: dict[str, Any]) -> dict[str, Any] | None:
    video_id = result.get("videoId")
    title = str(result.get("title", "")).strip()
    artists = _artist_text(result)
    if not video_id or not title or not artists:
        return None
    return {
        "video_id": video_id,
        "title": title,
        "artists": artists,
        "album": _album_name(result) or None,
        "duration": result.get("duration"),
        "thumbnail_url": _thumbnail(result),
        "url": f"https://music.youtube.com/watch?v={video_id}",
    }


def _exclusion_reason(
    title: str,
    *,
    album: str = "",
    artists: str = "",
    live: bool,
    covers: bool,
    remixes: bool,
) -> str | None:
    title_and_album = f"{title} {album}".casefold()
    normalized_artists = artists.casefold()
    if live and _LIVE_RE.search(title_and_album):
        return "excluded_live"
    if remixes and _REMIX_RE.search(title_and_album):
        return "excluded_remix"
    if covers and (
        _COVER_RE.search(title_and_album) or _COVER_RE.search(normalized_artists)
    ):
        return "excluded_cover"
    return None


def _is_excluded(
    title: str,
    *,
    album: str = "",
    artists: str = "",
    live: bool,
    covers: bool,
    remixes: bool,
) -> bool:
    """Reject unwanted versions using all catalogue metadata, not only the title."""
    return _exclusion_reason(
        title,
        album=album,
        artists=artists,
        live=live,
        covers=covers,
        remixes=remixes,
    ) is not None


def _looks_like_collection(candidate_title: str, result_title: str) -> bool:
    """Reject collection-style uploads when a normal single track was requested."""
    candidate = candidate_title.casefold()
    result = result_title.casefold()
    return any(term in result and term not in candidate for term in _COLLECTION_TERMS)


def _title_score(candidate_title: str, result_title: str) -> float:
    """Reward close titles and penalize noisy YouTube-style suffixes."""
    candidate_tokens = set(_TITLE_TOKEN_RE.findall(candidate_title.casefold()))
    result_tokens = set(_TITLE_TOKEN_RE.findall(result_title.casefold()))
    extra_tokens = max(0, len(result_tokens - candidate_tokens))
    penalty = min(28, extra_tokens * 2.5)
    return max(0.0, fuzz.token_set_ratio(candidate_title, result_title) - penalty)


def _artist_score(candidate_artist: str, result_artists: str) -> float:
    """Match artist spelling while still accepting punctuation and collaborator variants."""
    candidate = _normalize_identity(candidate_artist)
    result = _normalize_identity(result_artists)
    if not candidate or not result:
        return 0.0
    token_score = fuzz.token_set_ratio(candidate, result)
    compact_score = fuzz.ratio(candidate.replace(" ", ""), result.replace(" ", ""))
    return max(token_score, compact_score)


def _search_songs(query: str, limit: int) -> list[dict[str, Any]]:
    results = _client().search(query, filter="songs", limit=limit)
    songs: list[dict[str, Any]] = []
    seen_video_ids: set[str] = set()
    seen_track_keys: set[str] = set()

    for result in results:
        song = _serialize_song(result)
        if not song:
            continue
        identity = track_identity_key(song["title"], song["artists"])
        if song["video_id"] in seen_video_ids or identity in seen_track_keys:
            continue
        seen_video_ids.add(song["video_id"])
        seen_track_keys.add(identity)
        songs.append(song)
    return songs


async def search_songs(query: str, limit: int = 8) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_search_songs, query, limit)


def _youtube_cache_path() -> Path:
    root = Path(os.getenv("PLAYLISTMUSE_DATA_DIR", "data"))
    return root / "youtube_resolution_cache.sqlite3"


def _youtube_cache_key(candidate: dict[str, str], exclusions: dict[str, bool]) -> str:
    flags = "".join(
        "1" if exclusions.get(name, True) else "0"
        for name in ("exclude_live", "exclude_covers", "exclude_remixes")
    )
    identity = track_identity_key(
        candidate.get("title", ""), candidate.get("artist", "")
    )
    return f"{YOUTUBE_CACHE_VERSION}|{identity}|{flags}"


def _youtube_cache_connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or _youtube_cache_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS youtube_resolution_cache (
            cache_key TEXT PRIMARY KEY,
            payload TEXT,
            expires_at REAL NOT NULL
        )
        """
    )
    return connection


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


def _decorate_resolved_track(
    track: dict[str, Any], candidate: dict[str, str]
) -> dict[str, Any]:
    decorated = dict(track)
    decorated["description"] = candidate.get("description", "")
    decorated["reason"] = candidate.get("reason", "")
    source = str(candidate.get("source", "")).strip()
    if source:
        decorated["source"] = source
    lastfm_strategy = str(candidate.get("lastfm_strategy", "")).strip()
    if lastfm_strategy:
        decorated["lastfm_strategy"] = lastfm_strategy
    return decorated


def _set_resolution_diagnostic(diagnostic: dict[str, Any] | None) -> None:
    _THREAD_LOCAL.last_resolution_diagnostic = diagnostic


def _take_resolution_diagnostic() -> dict[str, Any] | None:
    diagnostic = getattr(_THREAD_LOCAL, "last_resolution_diagnostic", None)
    _THREAD_LOCAL.last_resolution_diagnostic = None
    return diagnostic if isinstance(diagnostic, dict) else None


def _resolution_failure_reason(stats: dict[str, int]) -> str:
    usable = stats.get("usable_results", 0)
    if stats.get("results", 0) == 0:
        return "no_results"
    if usable == 0:
        return "no_usable_results"
    excluded = sum(
        stats.get(name, 0)
        for name in ("excluded_live", "excluded_cover", "excluded_remix")
    )
    if excluded >= usable:
        return "recording_excluded"
    if stats.get("collection", 0) >= usable:
        return "collection_result"
    if stats.get("artist_mismatch", 0) > stats.get("title_mismatch", 0):
        return "artist_mismatch"
    if stats.get("title_mismatch", 0):
        return "title_mismatch"
    return "no_acceptable_match"


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
        exclusion_reason = _exclusion_reason(
            title,
            album=album,
            artists=artists,
            live=exclude_live,
            covers=exclude_covers,
            remixes=exclude_remixes,
        )
        if exclusion_reason:
            stats[exclusion_reason] = stats.get(exclusion_reason, 0) + 1
            continue
        if _looks_like_collection(candidate["title"], title):
            stats["collection"] = stats.get("collection", 0) + 1
            continue

        title_score = _title_score(candidate["title"], title)
        artist_score = _artist_score(candidate["artist"], artists)
        best_title_score = max(best_title_score, title_score)
        best_artist_score = max(best_artist_score, artist_score)
        if title_score < MIN_TITLE_SCORE:
            stats["title_mismatch"] = stats.get("title_mismatch", 0) + 1
            continue
        if artist_score < MIN_ARTIST_SCORE:
            stats["artist_mismatch"] = stats.get("artist_mismatch", 0) + 1
            continue

        score = title_score * 0.68 + artist_score * 0.32
        best_combined_score = max(best_combined_score, score)
        if best is None or score > best[0]:
            best = (score, result)

    if best is None:
        diagnostic = {
            "reason": _resolution_failure_reason(stats),
            "best_title_score": round(best_title_score, 1),
            "best_artist_score": round(best_artist_score, 1),
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
        diagnostic = {"reason": "serialization_failed", **stats}
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


def _metadata_rejection(candidate: dict[str, str], result: Any) -> dict[str, Any]:
    metadata = result.metadata
    return {
        **candidate,
        "unresolved_reason": "metadata_validation",
        "metadata_validation": {
            "status": result.status,
            "violations": list(result.violations),
            "source": metadata.source,
            "match_score": metadata.match_score,
            "confidence": metadata.confidence,
            "recording_mbid": metadata.recording_mbid,
            "release_group_mbid": metadata.release_group_mbid,
            "isrcs": list(metadata.isrcs),
            "original_release_date": metadata.original_release_date,
            "original_release_year": metadata.original_release_year,
            "artist_country": metadata.artist_country,
            "artist_area": metadata.artist_area,
            "matched_artist": metadata.matched_artist,
            "warnings": list(metadata.warnings),
        },
    }


def _youtube_resolution_concurrency() -> int:
    raw = os.getenv(
        "YOUTUBE_RESOLUTION_CONCURRENCY",
        str(DEFAULT_YOUTUBE_RESOLUTION_CONCURRENCY),
    )
    try:
        return max(1, min(8, int(raw)))
    except ValueError:
        return DEFAULT_YOUTUBE_RESOLUTION_CONCURRENCY


def _budget_exceeded_result(candidate: dict[str, str]) -> ValidationResult:
    return ValidationResult(
        status="unknown",
        violations=[],
        metadata=TrackMetadata(
            artist=str(candidate.get("artist", "")),
            title=str(candidate.get("title", "")),
            warnings=["Metadata lookup budget exceeded"],
        ),
    )


def _temporarily_unavailable(result: Any) -> bool:
    """Distinguish MusicBrainz outages from genuine unknown metadata."""
    if result.status != "unknown" or result.violations:
        return False
    return any(
        str(warning).startswith("Metadata lookup unavailable:")
        for warning in result.metadata.warnings
    )


def _metadata_retryable(result: ValidationResult, constraints: Any) -> bool:
    if _temporarily_unavailable(result):
        return False
    warnings = " ".join(str(item).casefold() for item in result.metadata.warnings)
    if "no musicbrainz match" in warnings or "match confidence is too low" in warnings:
        return True
    temporal_required = any(
        value is not None
        for value in (
            constraints.release_year,
            constraints.release_year_from,
            constraints.release_year_to,
        )
    )
    return (
        result.status == "unknown"
        and temporal_required
        and result.metadata.original_release_year is None
    )


def _metadata_artist_aliases(candidate: dict[str, str]) -> list[str]:
    canonical = " ".join(str(candidate.get("artist", "")).split())
    requested = " ".join(str(candidate.get("requested_artist", "")).split())
    aliases: list[str] = []
    seen = {_normalize_identity(canonical)} if canonical else set()

    def add(value: str) -> None:
        normalized = " ".join(str(value).split()).strip(" ,&-")
        key = _normalize_identity(normalized)
        if normalized and key and key not in seen:
            seen.add(key)
            aliases.append(normalized)

    add(requested)
    for source in (canonical, requested):
        parts = [part for part in _ARTIST_SPLIT_RE.split(source) if part]
        if parts:
            add(parts[0])
        for part in parts[1:]:
            add(part)
    return aliases[: max(0, MAX_METADATA_ARTIST_ATTEMPTS - 1)]


def _prefer_metadata_result(
    current: ValidationResult,
    alternative: ValidationResult,
) -> bool:
    if alternative.status == "valid" and current.status != "valid":
        return True
    if current.status == "valid":
        return False
    current_year = current.metadata.original_release_year
    alternative_year = alternative.metadata.original_release_year
    if current_year is None and alternative_year is not None:
        return True
    return alternative.metadata.match_score > current.metadata.match_score


def _canonicalize_fallback_metadata(
    result: ValidationResult,
    canonical_artist: str,
    alias: str,
) -> ValidationResult:
    result.metadata.artist = canonical_artist
    marker = f"MusicBrainz artist fallback used: {alias}"
    if marker not in result.metadata.warnings:
        result.metadata.warnings.append(marker)
    return result


def _log_unresolved_candidate(item: dict[str, Any]) -> None:
    artist = " ".join(str(item.get("artist", "")).split())[:180]
    title = " ".join(str(item.get("title", "")).split())[:220]
    reason = str(item.get("unresolved_reason") or "youtube_resolution")
    if reason == "youtube_resolution":
        details = item.get("youtube_resolution")
        LOGGER.info(
            "catalogue_candidate outcome=rejected layer=youtube artist=%r title=%r "
            "reason=%s details=%s",
            artist,
            title,
            str(details.get("reason", "unknown")) if isinstance(details, dict) else "unknown",
            details if isinstance(details, dict) else {},
        )
        return
    if reason in {"metadata_validation", "metadata_service_unavailable"}:
        validation = item.get("metadata_validation")
        catalogue = item.get("resolved_catalogue")
        LOGGER.info(
            "catalogue_candidate outcome=rejected layer=metadata artist=%r title=%r "
            "reason=%s resolved_catalogue=%s validation=%s",
            artist,
            title,
            reason,
            catalogue if isinstance(catalogue, dict) else {},
            validation if isinstance(validation, dict) else {},
        )


async def _metadata_filter(
    candidates: list[dict[str, str]],
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
        len(unique_candidates) * MAX_METADATA_ARTIST_ATTEMPTS
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
            artist = str(candidate.get("artist", "")).strip()
            title = str(candidate.get("title", "")).strip()
            cached = _read_cache(artist, title)
            if cached is not None:
                return validate_metadata(cached, constraints)
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

        for candidate in unique_candidates:
            canonical_artist = str(candidate.get("artist", "")).strip()
            result = await evaluate(candidate)
            if _metadata_retryable(result, constraints):
                for alias in _metadata_artist_aliases(candidate):
                    alternative_candidate = {**candidate, "artist": alias}
                    alternative = await evaluate(alternative_candidate)
                    if _prefer_metadata_result(result, alternative):
                        result = _canonicalize_fallback_metadata(
                            alternative,
                            canonical_artist,
                            alias,
                        )
                    if result.status == "valid":
                        break

            if result.status == "valid":
                copy = dict(candidate)
                copy["metadata_validation"] = asdict(result.metadata)  # type: ignore[assignment]
                accepted.append(copy)
            else:
                rejection = _metadata_rejection(candidate, result)
                if _temporarily_unavailable(result):
                    rejection["unresolved_reason"] = "metadata_service_unavailable"
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

    validated_candidates, metadata_rejected = await _metadata_filter(
        canonical_candidates
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
