"""Playlist-level policy parsing, normalization and deterministic enforcement."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.text_normalization import normalize_identity as _normalize

MIN_POLICY_CONFIDENCE = 0.85
_STRICT_MAJORITY_RE = re.compile(
    r"\b(?:pi[uù]\s+della\s+met[aà]|more\s+than\s+half|plus\s+de\s+la\s+moiti[eé]|"
    r"m[aá]s\s+de\s+la\s+mitad|mehr\s+als\s+die\s+h[aä]lfte)\b",
    re.IGNORECASE,
)
_EXCLUSIVE_ARTIST_RE = re.compile(
    r"\b(?:solo|soltanto|esclusivamente|only|exclusively|uniquement|seulement|"
    r"solamente|nur)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class NamedTrack:
    artist: str
    title: str


@dataclass(slots=True)
class PlaylistPolicy:
    required_tracks: list[NamedTrack] = field(default_factory=list)
    excluded_tracks: list[NamedTrack] = field(default_factory=list)
    quota_artists: list[str] = field(default_factory=list)
    minimum_allowed_artist_ratio: float | None = None
    maximum_allowed_artist_ratio: float | None = None
    minimum_allowed_artist_count: int | None = None
    maximum_allowed_artist_count: int | None = None
    strict_artist_majority: bool = False
    max_tracks_per_artist: int | None = None
    lyrics_language: str | None = None
    release_country: str | None = None
    target_market: str | None = None
    soundtrack_title: str | None = None
    soundtrack_type: str | None = None
    unsupported_verification: list[str] = field(default_factory=list)
    field_confidence: dict[str, float] = field(default_factory=dict)

    @property
    def has_artist_quota(self) -> bool:
        return bool(self.quota_artists) and any(
            (
                self.minimum_allowed_artist_ratio is not None,
                self.maximum_allowed_artist_ratio is not None,
                self.minimum_allowed_artist_count is not None,
                self.maximum_allowed_artist_count is not None,
                self.strict_artist_majority,
            )
        )

    @property
    def active(self) -> bool:
        return any(
            (
                self.required_tracks,
                self.excluded_tracks,
                self.has_artist_quota,
                self.max_tracks_per_artist is not None,
                self.lyrics_language,
                self.release_country,
                self.target_market,
                self.soundtrack_title,
            )
        )


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


def _clean_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value[:20]:
        name = " ".join(str(item).split()).strip(" .,-")[:180]
        key = _normalize(name)
        if name and key and key not in seen:
            seen.add(key)
            result.append(name)
    return result


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


def policy_from_payload(
    payload: dict[str, Any] | None,
    *,
    prompt: str = "",
) -> PlaylistPolicy:
    if not isinstance(payload, dict):
        return PlaylistPolicy()
    confidence = _confidence_map(payload)

    def value(field_name: str, cleaner):
        return cleaner(payload.get(field_name)) if _trusted(confidence, field_name) else None

    required = (
        _clean_tracks(payload.get("required_tracks"))
        if _trusted(confidence, "required_tracks")
        else []
    )
    excluded = (
        _clean_tracks(payload.get("excluded_tracks"))
        if _trusted(confidence, "excluded_tracks")
        else []
    )

    quota_artists = (
        _clean_names(payload.get("quota_artists"))
        if _trusted(confidence, "quota_artists")
        else []
    )
    quota_fields = (
        "minimum_allowed_artist_ratio",
        "maximum_allowed_artist_ratio",
        "minimum_allowed_artist_count",
        "maximum_allowed_artist_count",
    )
    has_trusted_quota = any(
        _trusted(confidence, field_name) for field_name in quota_fields
    )
    if (
        not quota_artists
        and has_trusted_quota
        and _trusted(confidence, "allowed_artists")
    ):
        quota_artists = _clean_names(payload.get("allowed_artists"))

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
        quota_artists=quota_artists,
        minimum_allowed_artist_ratio=value(
            "minimum_allowed_artist_ratio", _clean_ratio
        ),
        maximum_allowed_artist_ratio=value(
            "maximum_allowed_artist_ratio", _clean_ratio
        ),
        minimum_allowed_artist_count=value(
            "minimum_allowed_artist_count", _clean_count
        ),
        maximum_allowed_artist_count=value(
            "maximum_allowed_artist_count", _clean_count
        ),
        strict_artist_majority=bool(
            quota_artists and _STRICT_MAJORITY_RE.search(prompt)
        ),
        max_tracks_per_artist=value(
            "max_tracks_per_artist",
            lambda item: _clean_count(item, maximum=100),
        ),
        lyrics_language=lyrics_language,
        release_country=release_country,
        target_market=target_market,
        soundtrack_title=soundtrack_title,
        soundtrack_type=soundtrack_type,
        unsupported_verification=unsupported,
        field_confidence=confidence,
    )


def hard_allowed_artists(
    allowed_artists: list[str],
    policy: PlaylistPolicy,
    *,
    prompt: str,
) -> list[str]:
    """Remove quota targets from hard filtering unless the prompt is explicitly exclusive."""
    if not policy.has_artist_quota or _EXCLUSIVE_ARTIST_RE.search(prompt):
        return list(allowed_artists)
    quota_keys = {_normalize(artist) for artist in policy.quota_artists}
    return [
        artist
        for artist in allowed_artists
        if _normalize(artist) not in quota_keys
    ]


def apply_playlist_policy(
    draft: dict[str, Any],
    policy: PlaylistPolicy,
    *,
    allowed_artists: list[str] | None = None,
    requested_count: int,
) -> tuple[dict[str, Any], list[str]]:
    """Apply the integrated deterministic list-level policy implementation."""
    from backend.policy_consistency import apply_playlist_policy as integrated_apply

    return integrated_apply(
        draft,
        policy,
        allowed_artists=allowed_artists,
        requested_count=requested_count,
    )
