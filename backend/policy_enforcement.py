"""Request-scoped playlist policy persistence and catalogue selection."""

from __future__ import annotations

import math
import re
from contextvars import ContextVar
from typing import Any

_ACTIVE_POLICY: ContextVar[Any | None] = ContextVar(
    "playlistmuse_active_playlist_policy", default=None
)
_POLICY_BASE_TRACKS: ContextVar[tuple[dict[str, Any], ...]] = ContextVar(
    "playlistmuse_policy_base_tracks", default=()
)
_REPLACEMENT_MODE: ContextVar[bool] = ContextVar(
    "playlistmuse_replacement_mode", default=False
)
_REPLACEMENT_FINAL_COUNT: ContextVar[int] = ContextVar(
    "playlistmuse_replacement_final_count", default=0
)

_REPLACEMENT_LINE_RE = re.compile(
    r"^-\s*(?P<artist>.+?)\s+—\s+(?P<title>.+?)\s*$"
)
_CURRENT_REPLACEMENT_RE = re.compile(
    r"^Song being replaced:\s*(?P<artist>.+?)\s+—\s+(?P<title>.+?)\s*$",
    re.MULTILINE,
)


def track_artist(track: dict[str, Any]) -> str:
    return str(track.get("artist", track.get("artists", ""))).strip()


def track_title(track: dict[str, Any]) -> str:
    return str(track.get("title", "")).strip()


def named_track_matches(track: dict[str, Any], named: Any) -> bool:
    from backend.text_normalization import normalize_identity

    return (
        normalize_identity(track_artist(track)) == normalize_identity(named.artist)
        and normalize_identity(track_title(track)) == normalize_identity(named.title)
    )


def apply_track_positions(
    tracks: list[dict[str, Any]], policy: Any
) -> list[dict[str, Any]]:
    """Apply explicit absolute song placements without disturbing other relative order."""
    ordered = list(tracks)
    placements = list(getattr(policy, "track_positions", []) or [])
    for placement in placements:
        match_index = next(
            (
                index
                for index, track in enumerate(ordered)
                if named_track_matches(track, placement)
            ),
            None,
        )
        if match_index is None:
            continue
        track = ordered.pop(match_index)
        if placement.position == "first":
            target = 0
        elif placement.position == "last":
            target = len(ordered)
        else:
            target = min(max(0, int(placement.index or 1) - 1), len(ordered))
        ordered.insert(target, track)
    return ordered


def quota_artist_match(track: dict[str, Any], quota_artists: list[str]) -> bool:
    from backend.text_normalization import normalize_identity

    actual = f" {normalize_identity(track_artist(track))} "
    return any(
        f" {normalize_identity(artist)} " in actual
        for artist in quota_artists
        if normalize_identity(artist)
    )


def policy_minimum(policy: Any, playlist_size: int) -> int | None:
    minimum = policy.minimum_allowed_artist_count
    if policy.minimum_allowed_artist_ratio is not None:
        minimum = max(
            minimum or 0,
            math.ceil(playlist_size * policy.minimum_allowed_artist_ratio),
        )
    if policy.strict_artist_majority:
        minimum = max(minimum or 0, playlist_size // 2 + 1)
    return minimum


def policy_maximum(policy: Any, playlist_size: int) -> int | None:
    maximum = policy.maximum_allowed_artist_count
    if policy.maximum_allowed_artist_ratio is not None:
        ratio_max = math.floor(playlist_size * policy.maximum_allowed_artist_ratio)
        maximum = ratio_max if maximum is None else min(maximum, ratio_max)
    return maximum


def apply_playlist_policy(
    draft: dict[str, Any],
    policy: Any,
    *,
    allowed_artists: list[str] | None = None,
    requested_count: int,
) -> tuple[dict[str, Any], list[str]]:
    """Apply list policy and keep every required track inside the final cutoff."""
    del allowed_artists
    from backend.text_normalization import normalize_identity

    _ACTIVE_POLICY.set(policy)
    tracks = [dict(track) for track in draft.get("tracks", []) if isinstance(track, dict)]
    issues: list[str] = []

    if policy.excluded_tracks:
        tracks = [
            track
            for track in tracks
            if not any(
                named_track_matches(track, excluded)
                for excluded in policy.excluded_tracks
            )
        ]

    if policy.max_tracks_per_artist is not None:
        limited: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        for track in tracks:
            artist = normalize_identity(track_artist(track))
            if counts.get(artist, 0) >= policy.max_tracks_per_artist:
                continue
            counts[artist] = counts.get(artist, 0) + 1
            limited.append(track)
        tracks = limited

    required_tracks: list[dict[str, Any]] = []
    remaining = list(tracks)
    for required in policy.required_tracks:
        match_index = next(
            (
                index
                for index, track in enumerate(remaining)
                if named_track_matches(track, required)
            ),
            None,
        )
        if match_index is None:
            required_tracks.append(
                {
                    "artist": required.artist,
                    "title": required.title,
                    "description": "Explicitly requested track.",
                    "reason": (
                        "Included because it was explicitly required in the playlist request."
                    ),
                    "source": "required_constraint",
                }
            )
        else:
            required_tracks.append(remaining.pop(match_index))
    tracks = required_tracks + remaining

    maximum = policy_maximum(policy, requested_count)
    if policy.quota_artists and maximum is not None:
        bounded: list[dict[str, Any]] = []
        quota_count = 0
        for track in tracks:
            is_required = any(
                named_track_matches(track, required)
                for required in policy.required_tracks
            )
            is_quota = quota_artist_match(track, policy.quota_artists)
            if is_quota and quota_count >= maximum and not is_required:
                continue
            if is_quota:
                quota_count += 1
            bounded.append(track)
        tracks = bounded

    tracks = apply_track_positions(tracks[:requested_count], policy)
    quota_count = (
        sum(quota_artist_match(track, policy.quota_artists) for track in tracks)
        if policy.quota_artists
        else 0
    )
    total = len(tracks)
    minimum = policy_minimum(policy, requested_count)

    if policy.quota_artists and minimum is not None and quota_count < minimum:
        issues.append(f"quota artist minimum unmet: {quota_count}/{minimum}")
    if policy.quota_artists and maximum is not None and quota_count > maximum:
        issues.append(f"quota artist maximum exceeded: {quota_count}/{maximum}")
    if len(policy.required_tracks) > requested_count:
        issues.append("required tracks exceed requested playlist size")
    if policy.max_tracks_per_artist and policy.quota_artists:
        capacity = policy.max_tracks_per_artist * len(policy.quota_artists)
        if minimum is not None and minimum > capacity:
            issues.append(
                f"artist quota is impossible: minimum {minimum}, capacity {capacity}"
            )
    if total < requested_count:
        issues.append(f"policy filtering left {total} of {requested_count} candidates")
    issues.extend(
        f"verification unavailable: {name}"
        for name in policy.unsupported_verification
    )

    result = dict(draft)
    result["tracks"] = tracks
    return result, issues


def parse_replacement_tracks(prompt: str) -> tuple[list[dict[str, str]], int]:
    current_match = _CURRENT_REPLACEMENT_RE.search(prompt)
    current_key = (
        (
            current_match.group("artist").strip().casefold(),
            current_match.group("title").strip().casefold(),
        )
        if current_match
        else None
    )
    section = (
        prompt.split("Songs to avoid:\n", 1)[1]
        if "Songs to avoid:\n" in prompt
        else ""
    )
    tracks: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line in section.splitlines():
        match = _REPLACEMENT_LINE_RE.match(line.strip())
        if not match:
            continue
        artist = match.group("artist").strip()
        title = match.group("title").strip()
        key = (artist.casefold(), title.casefold())
        if key == current_key or key in seen:
            continue
        seen.add(key)
        tracks.append({"artists": artist, "title": title})
    return tracks, len(tracks) + 1


def replacement_candidate_valid(
    candidate: dict[str, Any],
    base_tracks: list[dict[str, Any]],
    policy: Any,
    playlist_size: int,
) -> bool:
    from backend.text_normalization import normalize_identity

    if any(named_track_matches(candidate, item) for item in policy.excluded_tracks):
        return False

    final_tracks = [*base_tracks, candidate]
    if policy.max_tracks_per_artist is not None:
        candidate_artist = normalize_identity(track_artist(candidate))
        artist_count = sum(
            normalize_identity(track_artist(track)) == candidate_artist
            for track in final_tracks
        )
        if artist_count > policy.max_tracks_per_artist:
            return False

    if any(
        not any(named_track_matches(track, required) for track in final_tracks)
        for required in policy.required_tracks
    ):
        return False

    if policy.quota_artists:
        quota_count = sum(
            quota_artist_match(track, policy.quota_artists)
            for track in final_tracks
        )
        minimum = policy_minimum(policy, playlist_size)
        maximum = policy_maximum(policy, playlist_size)
        if minimum is not None and quota_count < minimum:
            return False
        if maximum is not None and quota_count > maximum:
            return False
    return True


def select_resolved_tracks(
    resolved: list[dict[str, Any]],
    *,
    youtube: Any,
    artist_matches: Any,
    quota_deficits: Any,
) -> list[dict[str, Any]]:
    """Select only returned tracks while reserving capacity for unmet policy."""
    from backend import generation_runtime as runtime

    requested = runtime._REQUESTED_SESSION_COUNT.get()
    if requested <= 0:
        return resolved

    policy = _ACTIVE_POLICY.get()
    base_tracks = list(_POLICY_BASE_TRACKS.get())
    if _REPLACEMENT_MODE.get():
        playlist_size = _REPLACEMENT_FINAL_COUNT.get() or len(base_tracks) + 1
        quotas = list(runtime._ACTIVE_RESOLUTION_QUOTAS.get())
        valid = [
            track
            for track in resolved
            if (
                policy is None
                or replacement_candidate_valid(
                    track,
                    base_tracks,
                    policy,
                    playlist_size,
                )
            )
            and not quota_deficits([*base_tracks, track], quotas)
        ]
        return sorted(
            valid,
            key=lambda item: runtime._diversity_rank(item, base_tracks),
        )[:requested]

    accepted = list(runtime._RESOLVED_SESSION_TRACKS.get())
    remaining_capacity = max(0, requested - len(accepted))
    if remaining_capacity <= 0:
        return []

    existing = [*base_tracks, *accepted]
    accepted_keys = {
        youtube.track_identity_key(track_title(track), track_artist(track))
        for track in existing
    }
    fresh: list[dict[str, Any]] = []
    for track in resolved:
        key = youtube.track_identity_key(track_title(track), track_artist(track))
        if key and key not in accepted_keys:
            accepted_keys.add(key)
            fresh.append(track)

    if policy is not None and policy.excluded_tracks:
        fresh = [
            track
            for track in fresh
            if not any(
                named_track_matches(track, item)
                for item in policy.excluded_tracks
            )
        ]

    selected: list[dict[str, Any]] = []

    def can_add(track: dict[str, Any]) -> bool:
        if len(selected) >= remaining_capacity:
            return False
        if policy is None:
            return True
        combined = [*existing, *selected]
        if policy.max_tracks_per_artist is not None:
            from backend.text_normalization import normalize_identity

            artist = normalize_identity(track_artist(track))
            count = sum(
                normalize_identity(track_artist(item)) == artist
                for item in combined
            )
            if count >= policy.max_tracks_per_artist:
                return False
        maximum = policy_maximum(policy, requested)
        if policy.quota_artists and maximum is not None:
            quota_count = sum(
                quota_artist_match(item, policy.quota_artists)
                for item in combined
            )
            if (
                quota_artist_match(track, policy.quota_artists)
                and quota_count >= maximum
            ):
                return False
        return True

    def take(track: dict[str, Any]) -> bool:
        if track not in fresh or not can_add(track):
            return False
        fresh.remove(track)
        selected.append(track)
        return True

    if policy is not None:
        for required in policy.required_tracks:
            if any(
                named_track_matches(track, required)
                for track in [*existing, *selected]
            ):
                continue
            candidate = next(
                (
                    track
                    for track in fresh
                    if named_track_matches(track, required)
                ),
                None,
            )
            if candidate is not None:
                take(candidate)

    quotas = list(runtime._ACTIVE_RESOLUTION_QUOTAS.get())
    while len(selected) < remaining_capacity:
        deficits = quota_deficits([*existing, *selected], quotas)
        if not deficits:
            break
        candidate = min(
            (
                track
                for track in fresh
                if any(
                    artist_matches(track_artist(track), deficit.artist)
                    for deficit in deficits
                )
                and can_add(track)
            ),
            key=lambda item: runtime._diversity_rank(
                item,
                [*existing, *selected],
            ),
            default=None,
        )
        if candidate is None or not take(candidate):
            break

    if policy is not None and policy.quota_artists:
        minimum = policy_minimum(policy, requested)
        while minimum is not None and len(selected) < remaining_capacity:
            quota_count = sum(
                quota_artist_match(track, policy.quota_artists)
                for track in [*existing, *selected]
            )
            if quota_count >= minimum:
                break
            candidate = min(
                (
                    track
                    for track in fresh
                    if quota_artist_match(track, policy.quota_artists)
                    and can_add(track)
                ),
                key=lambda item: runtime._diversity_rank(
                    item,
                    [*existing, *selected],
                ),
                default=None,
            )
            if candidate is None or not take(candidate):
                break

    missing_required = 0
    if policy is not None:
        missing_required = sum(
            1
            for required in policy.required_tracks
            if not any(
                named_track_matches(track, required)
                for track in [*existing, *selected]
            )
        )
    independent_missing = sum(
        deficit.minimum
        for deficit in quota_deficits([*existing, *selected], quotas)
    )
    shared_missing = 0
    if policy is not None and policy.quota_artists:
        minimum = policy_minimum(policy, requested)
        if minimum is not None:
            shared_count = sum(
                quota_artist_match(track, policy.quota_artists)
                for track in [*existing, *selected]
            )
            shared_missing = max(0, minimum - shared_count)
    reserved_slots = max(missing_required, independent_missing, shared_missing)
    general_capacity = max(
        0,
        remaining_capacity - len(selected) - reserved_slots,
    )

    for track in sorted(
        fresh,
        key=lambda item: runtime._diversity_rank(
            item,
            [*existing, *selected],
        ),
    ):
        if len(selected) >= remaining_capacity or general_capacity <= 0:
            break
        if take(track):
            general_capacity -= 1

    runtime._RESOLVED_SESSION_TRACKS.set((*accepted, *selected))
    return selected
