"""Final capacity guard for request-scoped catalogue selection."""

from __future__ import annotations

from typing import Any

from backend.policy_enforcement import (
    _ACTIVE_POLICY,
    _POLICY_BASE_TRACKS,
    _REPLACEMENT_MODE,
    named_track_matches,
    policy_minimum,
    quota_artist_match,
    select_resolved_tracks,
)


def _missing_capacity(
    tracks: list[dict[str, Any]],
    *,
    policy: Any | None,
    quotas: list[Any],
    quota_deficits: Any,
    requested: int,
) -> int:
    missing_required = 0
    if policy is not None:
        missing_required = sum(
            1
            for required in policy.required_tracks
            if not any(named_track_matches(track, required) for track in tracks)
        )

    independent_missing = sum(
        deficit.minimum for deficit in quota_deficits(tracks, quotas)
    )
    shared_missing = 0
    if policy is not None and policy.quota_artists:
        minimum = policy_minimum(policy, requested)
        if minimum is not None:
            represented = sum(
                quota_artist_match(track, policy.quota_artists)
                for track in tracks
            )
            shared_missing = max(0, minimum - represented)

    return missing_required + max(independent_missing, shared_missing)


def _respect_exact_artist_caps(
    tracks: list[dict[str, Any]],
    existing: list[dict[str, Any]],
    exact_quotas: list[Any],
    *,
    artist_matches: Any,
) -> list[dict[str, Any]]:
    """Drop resolved surplus tracks before they can exceed explicit final artist counts."""
    if not exact_quotas:
        return tracks

    counts = {quota.artist: 0 for quota in exact_quotas}
    for track in existing:
        artist = str(track.get("artists", track.get("artist", "")))
        for quota in exact_quotas:
            if artist_matches(artist, quota.artist):
                counts[quota.artist] += 1

    kept: list[dict[str, Any]] = []
    for track in tracks:
        artist = str(track.get("artists", track.get("artist", "")))
        matched = [
            quota for quota in exact_quotas if artist_matches(artist, quota.artist)
        ]
        if any(counts[quota.artist] >= quota.count for quota in matched):
            continue
        kept.append(track)
        for quota in matched:
            counts[quota.artist] += 1
    return kept


def guarded_select_resolved_tracks(
    resolved: list[dict[str, Any]],
    *,
    youtube: Any,
    artist_matches: Any,
    quota_deficits: Any,
) -> list[dict[str, Any]]:
    """Keep enough unfilled slots for every still-missing independent rule."""
    from backend import generation_runtime as runtime

    before = list(runtime._RESOLVED_SESSION_TRACKS.get())
    selected = select_resolved_tracks(
        resolved,
        youtube=youtube,
        artist_matches=artist_matches,
        quota_deficits=quota_deficits,
    )
    if _REPLACEMENT_MODE.get():
        return selected

    requested = runtime._REQUESTED_SESSION_COUNT.get()
    if requested <= 0 or not selected:
        return selected

    policy = _ACTIVE_POLICY.get()
    quotas = list(runtime._ACTIVE_RESOLUTION_QUOTAS.get())
    exact_quotas = list(runtime._ACTIVE_EXACT_ARTIST_QUOTAS.get())
    base_tracks = list(_POLICY_BASE_TRACKS.get())
    selected = _respect_exact_artist_caps(
        selected,
        [*base_tracks, *before],
        exact_quotas,
        artist_matches=artist_matches,
    )
    kept = list(selected)

    while kept:
        combined = [*base_tracks, *before, *kept]
        missing = _missing_capacity(
            combined,
            policy=policy,
            quotas=quotas,
            quota_deficits=quota_deficits,
            requested=requested,
        )
        open_slots = max(0, requested - len(before) - len(kept))
        if open_slots >= missing:
            break

        removable_index = None
        for index in range(len(kept) - 1, -1, -1):
            without = [*base_tracks, *before, *kept[:index], *kept[index + 1 :]]
            if _missing_capacity(
                without,
                policy=policy,
                quotas=quotas,
                quota_deficits=quota_deficits,
                requested=requested,
            ) == missing:
                removable_index = index
                break
        if removable_index is None:
            break
        kept.pop(removable_index)

    runtime._RESOLVED_SESSION_TRACKS.set((*before, *kept))
    return kept
