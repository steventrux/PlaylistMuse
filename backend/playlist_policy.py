"""Playlist-level policy parsing, normalization and deterministic enforcement."""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

MIN_POLICY_CONFIDENCE = 0.85


@dataclass(slots=True)
class NamedTrack:
    artist: str
    title: str


@dataclass(slots=True)
class PlaylistPolicy:
    required_tracks: list[NamedTrack] = field(default_factory=list)
    excluded_tracks: list[NamedTrack] = field(default_factory=list)
    minimum_allowed_artist_ratio: float | None = None
    maximum_allowed_artist_ratio: float | None = None
    minimum_allowed_artist_count: int | None = None
    maximum_allowed_artist_count: int | None = None
    max_tracks_per_artist: int | None = None
    lyrics_language: str | None = None
    release_country: str | None = None
    target_market: str | None = None
    soundtrack_title: str | None = None
    soundtrack_type: str | None = None
    unsupported_verification: list[str] = field(default_factory=list)
    field_confidence: dict[str, float] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return any(
            (
                self.required_tracks,
                self.excluded_tracks,
                self.minimum_allowed_artist_ratio is not None,
                self.maximum_allowed_artist_ratio is not None,
                self.minimum_allowed_artist_count is not None,
                self.maximum_allowed_artist_count is not None,
                self.max_tracks_per_artist is not None,
                self.lyrics_language,
                self.release_country,
                self.target_market,
                self.soundtrack_title,
            )
        )


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value).casefold())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", plain))


def _confidence_map(payload: dict[str, Any]) -> dict[str, float]:
    raw = payload.get("field_confidence")
    result: dict[str, float] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            try:
                result[str(key)] = max(0.0, min(1.0, float(value)))
            except (TypeError, ValueError):
                continue
    return result


def _trusted(confidence: dict[str, float], field_name: str) -> bool:
    return confidence.get(field_name, 0.0) >= MIN_POLICY_CONFIDENCE


def _clean_tracks(value: Any) -> list[NamedTrack]:
    if not isinstance(value, list):
        return []
    cleaned: list[NamedTrack] = []
    seen: set[str] = set()
    for item in value[:30]:
        if not isinstance(item, dict):
            continue
        artist = " ".join(str(item.get("artist", "")).split()).strip(" .,-")[:180]
        title = " ".join(str(item.get("title", "")).split()).strip(" .,-")[:220]
        key = f"{_normalize(artist)}|{_normalize(title)}"
        if artist and title and key not in seen:
            seen.add(key)
            cleaned.append(NamedTrack(artist=artist, title=title))
    return cleaned


def _clean_ratio(value: Any) -> float | None:
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return None
    if ratio > 1:
        ratio /= 100
    return max(0.0, min(1.0, ratio))


def _clean_count(value: Any, *, maximum: int = 500) -> int | None:
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, min(maximum, count))


def _clean_text(value: Any, limit: int = 180) -> str | None:
    text = " ".join(str(value or "").split()).strip()
    return text[:limit] or None


def policy_from_payload(payload: dict[str, Any] | None) -> PlaylistPolicy:
    if not isinstance(payload, dict):
        return PlaylistPolicy()
    confidence = _confidence_map(payload)

    def value(field_name: str, cleaner):
        return cleaner(payload.get(field_name)) if _trusted(confidence, field_name) else None

    required = _clean_tracks(payload.get("required_tracks")) if _trusted(confidence, "required_tracks") else []
    excluded = _clean_tracks(payload.get("excluded_tracks")) if _trusted(confidence, "excluded_tracks") else []
    unsupported: list[str] = []
    lyrics_language = value("lyrics_language", _clean_text)
    release_country = value("release_country", _clean_text)
    target_market = value("target_market", _clean_text)
    soundtrack_title = value("soundtrack_title", _clean_text)
    soundtrack_type = value("soundtrack_type", _clean_text)
    if lyrics_language:
        unsupported.append("lyrics_language")
    if target_market:
        unsupported.append("target_market")
    if soundtrack_title:
        unsupported.append("soundtrack_membership")

    return PlaylistPolicy(
        required_tracks=required,
        excluded_tracks=excluded,
        minimum_allowed_artist_ratio=value("minimum_allowed_artist_ratio", _clean_ratio),
        maximum_allowed_artist_ratio=value("maximum_allowed_artist_ratio", _clean_ratio),
        minimum_allowed_artist_count=value("minimum_allowed_artist_count", _clean_count),
        maximum_allowed_artist_count=value("maximum_allowed_artist_count", _clean_count),
        max_tracks_per_artist=value("max_tracks_per_artist", lambda item: _clean_count(item, maximum=100)),
        lyrics_language=lyrics_language,
        release_country=release_country,
        target_market=target_market,
        soundtrack_title=soundtrack_title,
        soundtrack_type=soundtrack_type,
        unsupported_verification=unsupported,
        field_confidence=confidence,
    )


def _track_key(artist: str, title: str) -> str:
    return f"{_normalize(artist)}|{_normalize(title)}"


def _artist_key(track: dict[str, Any]) -> str:
    return _normalize(str(track.get("artist", track.get("artists", ""))))


def _matches_named_track(track: dict[str, Any], named: NamedTrack) -> bool:
    return _track_key(str(track.get("artist", "")), str(track.get("title", ""))) == _track_key(named.artist, named.title)


def _required_candidate(named: NamedTrack) -> dict[str, str]:
    return {
        "artist": named.artist,
        "title": named.title,
        "description": "Explicitly requested track.",
        "reason": "Included because it was explicitly required in the playlist request.",
        "source": "required_constraint",
    }


def _allowed_artist_match(track: dict[str, Any], allowed_artists: list[str]) -> bool:
    actual = f" {_artist_key(track)} "
    return any(f" {_normalize(artist)} " in actual for artist in allowed_artists if _normalize(artist))


def apply_playlist_policy(
    draft: dict[str, Any],
    policy: PlaylistPolicy,
    *,
    allowed_artists: list[str],
    requested_count: int,
) -> tuple[dict[str, Any], list[str]]:
    """Apply deterministic list-level rules and return non-fatal feasibility issues."""
    tracks = [dict(track) for track in draft.get("tracks", []) if isinstance(track, dict)]
    issues: list[str] = []

    if policy.excluded_tracks:
        tracks = [
            track
            for track in tracks
            if not any(_matches_named_track(track, excluded) for excluded in policy.excluded_tracks)
        ]

    if policy.max_tracks_per_artist is not None:
        limited: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        for track in tracks:
            artist = _artist_key(track)
            if counts.get(artist, 0) >= policy.max_tracks_per_artist:
                continue
            counts[artist] = counts.get(artist, 0) + 1
            limited.append(track)
        tracks = limited

    existing = {_track_key(str(track.get("artist", "")), str(track.get("title", ""))) for track in tracks}
    required_candidates: list[dict[str, Any]] = []
    for required in policy.required_tracks:
        key = _track_key(required.artist, required.title)
        if key not in existing:
            required_candidates.append(_required_candidate(required))
            existing.add(key)
    if required_candidates:
        tracks = required_candidates + tracks

    tracks = tracks[:requested_count]
    allowed_count = sum(_allowed_artist_match(track, allowed_artists) for track in tracks) if allowed_artists else 0
    total = len(tracks)

    minimum = policy.minimum_allowed_artist_count
    if policy.minimum_allowed_artist_ratio is not None:
        minimum = max(minimum or 0, math.ceil(requested_count * policy.minimum_allowed_artist_ratio))
    maximum = policy.maximum_allowed_artist_count
    if policy.maximum_allowed_artist_ratio is not None:
        ratio_max = math.floor(requested_count * policy.maximum_allowed_artist_ratio)
        maximum = ratio_max if maximum is None else min(maximum, ratio_max)

    if allowed_artists and minimum is not None and allowed_count < minimum:
        issues.append(f"allowed artist minimum unmet: {allowed_count}/{minimum}")
    if allowed_artists and maximum is not None and allowed_count > maximum:
        issues.append(f"allowed artist maximum exceeded: {allowed_count}/{maximum}")
    if len(policy.required_tracks) > requested_count:
        issues.append("required tracks exceed requested playlist size")
    if policy.max_tracks_per_artist and allowed_artists:
        capacity = policy.max_tracks_per_artist * len(allowed_artists)
        if minimum is not None and minimum > capacity:
            issues.append(f"artist quota is impossible: minimum {minimum}, capacity {capacity}")
    if total < requested_count:
        issues.append(f"policy filtering left {total} of {requested_count} candidates")
    issues.extend(f"verification unavailable: {name}" for name in policy.unsupported_verification)

    result = dict(draft)
    result["tracks"] = tracks
    return result, issues
