"""Resolve conflicts between required tracks and per-artist limits."""

from __future__ import annotations

from collections import Counter
from typing import Any

from backend.policy_enforcement import (
    apply_playlist_policy as _base_apply_playlist_policy,
    named_track_matches,
    policy_maximum,
    policy_minimum,
    quota_artist_match,
    track_artist,
)
from backend.text_normalization import normalize_identity

_DYNAMIC_ISSUE_PREFIXES = (
    "quota artist minimum unmet:",
    "quota artist maximum exceeded:",
    "policy filtering left ",
)


def _required_artist_counts(policy: Any) -> Counter[str]:
    return Counter(
        normalize_identity(required.artist)
        for required in policy.required_tracks
        if normalize_identity(required.artist)
    )


def _raise_required_limit_conflict(policy: Any, maximum: int) -> None:
    required_counts = _required_artist_counts(policy)
    conflicts = {
        artist: count
        for artist, count in required_counts.items()
        if count > maximum
    }
    if not conflicts:
        return

    display_names: dict[str, str] = {}
    for required in policy.required_tracks:
        key = normalize_identity(required.artist)
        if key:
            display_names.setdefault(key, required.artist)
    details = ", ".join(
        f"{display_names.get(artist, artist)} requires {count} tracks but the maximum is {maximum}"
        for artist, count in sorted(conflicts.items())
    )
    raise ValueError(
        "Required tracks are incompatible with the maximum tracks per artist: "
        f"{details}."
    )


def _enforce_required_artist_limit(
    tracks: list[dict[str, Any]],
    policy: Any,
) -> list[dict[str, Any]]:
    maximum = policy.max_tracks_per_artist
    if maximum is None:
        return tracks

    _raise_required_limit_conflict(policy, maximum)
    required_counts = _required_artist_counts(policy)
    optional_counts: Counter[str] = Counter()
    kept: list[dict[str, Any]] = []

    for track in tracks:
        artist = normalize_identity(track_artist(track))
        is_required = any(
            named_track_matches(track, required)
            for required in policy.required_tracks
        )
        if is_required:
            kept.append(track)
            continue

        optional_capacity = max(0, maximum - required_counts.get(artist, 0))
        if optional_counts[artist] >= optional_capacity:
            continue
        optional_counts[artist] += 1
        kept.append(track)

    return kept


def _refresh_dynamic_issues(
    issues: list[str],
    tracks: list[dict[str, Any]],
    policy: Any,
    requested_count: int,
) -> list[str]:
    refreshed = [
        issue
        for issue in issues
        if not issue.startswith(_DYNAMIC_ISSUE_PREFIXES)
    ]
    quota_count = (
        sum(quota_artist_match(track, policy.quota_artists) for track in tracks)
        if policy.quota_artists
        else 0
    )
    minimum = policy_minimum(policy, requested_count)
    maximum = policy_maximum(policy, requested_count)

    if policy.quota_artists and minimum is not None and quota_count < minimum:
        refreshed.append(f"quota artist minimum unmet: {quota_count}/{minimum}")
    if policy.quota_artists and maximum is not None and quota_count > maximum:
        refreshed.append(f"quota artist maximum exceeded: {quota_count}/{maximum}")
    if len(tracks) < requested_count:
        refreshed.append(
            f"policy filtering left {len(tracks)} of {requested_count} candidates"
        )
    return refreshed


def apply_playlist_policy(
    draft: dict[str, Any],
    policy: Any,
    *,
    allowed_artists: list[str] | None = None,
    requested_count: int,
) -> tuple[dict[str, Any], list[str]]:
    """Apply policy while reserving artist capacity for every required track."""
    result, issues = _base_apply_playlist_policy(
        draft,
        policy,
        allowed_artists=allowed_artists,
        requested_count=requested_count,
    )
    tracks = [
        dict(track)
        for track in result.get("tracks", [])
        if isinstance(track, dict)
    ]
    tracks = _enforce_required_artist_limit(tracks, policy)

    updated = dict(result)
    updated["tracks"] = tracks
    return updated, _refresh_dynamic_issues(
        issues,
        tracks,
        policy,
        requested_count,
    )
