"""Deterministic PlaylistMuse policy for explicit ReccoBeats popularity requests."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

POPULAR_MINIMUM = 60
LESS_KNOWN_MAXIMUM = 30


def popularity_value(track: dict[str, Any]) -> int | None:
    value = track.get("popularity")
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalized_preference(preference: Any) -> str:
    value = str(preference or "neutral").strip().casefold()
    return value if value in {"popular", "less_known"} else "neutral"


def satisfies_popularity(score: int | None, preference: Any) -> bool:
    """Return whether a known score satisfies PlaylistMuse's explicit absolute band."""
    normalized = normalized_preference(preference)
    if normalized == "neutral":
        return True
    if score is None:
        return False
    if normalized == "popular":
        return score >= POPULAR_MINIMUM
    return score <= LESS_KNOWN_MAXIMUM


def filter_absolute_popularity(
    tracks: Iterable[dict[str, Any]],
    preference: Any,
) -> list[dict[str, Any]]:
    normalized = normalized_preference(preference)
    copied = [dict(track) for track in tracks]
    if normalized == "neutral":
        return copied
    return [
        track
        for track in copied
        if satisfies_popularity(popularity_value(track), normalized)
    ]


def popularity_policy_label(preference: Any) -> str:
    normalized = normalized_preference(preference)
    if normalized == "popular":
        return f">={POPULAR_MINIMUM}"
    if normalized == "less_known":
        return f"<={LESS_KNOWN_MAXIMUM}"
    return "neutral"
