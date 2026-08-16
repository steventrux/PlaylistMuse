"""Request-scoped helpers for absolute popularity enforcement after LLM generation."""

from __future__ import annotations

from typing import Any

from backend.popularity_policy import popularity_value, satisfies_popularity
from backend.text_normalization import normalize_identity


def _identity(track: dict[str, Any]) -> tuple[str, str]:
    artist = str(track.get("artist") or track.get("artists") or "")
    title = str(track.get("title") or "")
    return normalize_identity(artist), normalize_identity(title)


def is_required_track(track: dict[str, Any]) -> bool:
    """Mandatory named tracks outrank the general popularity preference."""
    try:
        from backend.policy_enforcement import _ACTIVE_POLICY, named_track_matches

        policy = _ACTIVE_POLICY.get()
        if policy is None:
            return False
        return any(
            named_track_matches(track, required)
            for required in getattr(policy, "required_tracks", ())
        )
    except Exception:
        return False


def partition_absolute_popularity(
    tracks: list[dict[str, Any]],
    preference: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for item in tracks:
        track = dict(item)
        score = popularity_value(track)
        if is_required_track(track) or satisfies_popularity(score, preference):
            accepted.append(track)
            continue
        track["unresolved_reason"] = "popularity_validation"
        rejected.append(track)
    return accepted, rejected


def merge_identity_locked_tracks(
    primary: list[dict[str, Any]],
    fallback: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for track in [*primary, *fallback]:
        key = _identity(track)
        if not all(key) or key in seen:
            continue
        seen.add(key)
        merged.append(dict(track))
        if len(merged) >= limit:
            break
    return merged


async def revalidate_creative_and_policy(
    config: Any,
    draft: dict[str, Any],
    *,
    requested_count: int,
) -> dict[str, Any]:
    """Run the existing creative and playlist policy on identity-locked Recco selections."""
    from backend.creative_intent import assess_creative_fit
    from backend.policy_consistency import apply_playlist_policy
    from backend.policy_enforcement import _ACTIVE_POLICY

    updated = dict(draft)
    tracks = [
        dict(track)
        for track in updated.get("tracks", [])
        if isinstance(track, dict)
    ]
    conflicts = await assess_creative_fit(config, tracks)
    if conflicts:
        conflict_by_index = {conflict.index: conflict for conflict in conflicts}
        kept: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for index, track in enumerate(tracks, start=1):
            conflict = conflict_by_index.get(index)
            if conflict is None:
                kept.append(track)
                continue
            rejected.append(
                {
                    **track,
                    "unresolved_reason": "creative_intent_validation",
                    "creative_intent_reason": conflict.reason,
                    "creative_intent_confidence": conflict.confidence,
                }
            )
        tracks = kept
        previous = [
            dict(item)
            for item in updated.get("creative_intent_rejected", [])
            if isinstance(item, dict)
        ]
        updated["creative_intent_rejected"] = [*previous, *rejected]

    updated["tracks"] = tracks
    policy = _ACTIVE_POLICY.get()
    if policy is not None:
        updated, _ = apply_playlist_policy(
            updated,
            policy,
            requested_count=max(1, int(requested_count)),
        )
    return updated
