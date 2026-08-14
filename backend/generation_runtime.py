"""Public generation runtime using the proven low-latency orchestration path."""

from __future__ import annotations

import time
from typing import Any

from backend import generation_runtime_core as _core
from backend.popularity_intent import active_popularity_intent
from backend.reccobeats_guidance import reccobeats_guidance

# Keep the public/runtime symbols stable while routing actual generation through
# the pre-advanced-Recco orchestration measured around 60–70 seconds.
_ACTIVE_RESOLUTION_QUOTAS = _core._ACTIVE_RESOLUTION_QUOTAS
_ACTIVE_EXACT_ARTIST_QUOTAS = _core._ACTIVE_EXACT_ARTIST_QUOTAS
_RESOLVED_SESSION_TRACKS = _core._RESOLVED_SESSION_TRACKS
_REQUESTED_SESSION_COUNT = _core._REQUESTED_SESSION_COUNT
_LAST_INTERPRETED_CONSTRAINTS = _core._LAST_INTERPRETED_CONSTRAINTS

MAX_CREATIVE_REPAIR_ROUNDS = _core.MAX_CREATIVE_REPAIR_ROUNDS
_stage_name = _core._stage_name
_creative_repair_rounds = _core._creative_repair_rounds
_constraint_source = _core._constraint_source
_quota_replenishment_guidance = _core._quota_replenishment_guidance
_numeric_quota_replenishment_guidance = _core._numeric_quota_replenishment_guidance
_hard_constraint_guidance = _core._hard_constraint_guidance
_optimized_replenishment_request = _core._optimized_replenishment_request
_repair_quota_prompt = _core._repair_quota_prompt
_reset_resolution_session = _core._reset_resolution_session
_cap_buffered_quotas_at_exact_counts = _core._cap_buffered_quotas_at_exact_counts
_album_key = _core._album_key
_log_stage = _core._log_stage
_reccobeats_replenishment_guidance = reccobeats_guidance

discover_from_anchors = _core.discover_from_anchors
discover_for_seed = _core.discover_for_seed


def _popularity_value(track: dict[str, Any]) -> int | None:
    value = track.get("popularity")
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _diversity_rank(track: dict[str, Any], existing: list[dict[str, Any]]) -> tuple[Any, ...]:
    """Retain compatibility for explicit tests; baseline runtime does not activate this intent."""
    base = _core._diversity_rank(track, existing)
    intent = active_popularity_intent()
    if not intent.active:
        return base
    score = _popularity_value(track)
    if score is None:
        return (1, 0, *base)
    popularity_rank = -score if str(intent.preference).casefold() == "popular" else score
    return (0, popularity_rank, *base)


async def generate_playlist_draft(
    config: Any,
    prompt: str,
    count: int,
) -> dict[str, Any]:
    """Generate with the proven baseline path; advanced Recco orchestration is disabled."""
    return await _core.generate_playlist_draft(config, prompt, count)


def _select_resolved_tracks(
    resolved: list[dict[str, Any]],
    *,
    youtube: Any,
    artist_matches: Any,
    quota_deficits: Any,
) -> list[dict[str, Any]]:
    from backend.selection_guard import guarded_select_resolved_tracks

    return guarded_select_resolved_tracks(
        resolved,
        youtube=youtube,
        artist_matches=artist_matches,
        quota_deficits=quota_deficits,
    )


async def resolve_candidates(
    candidates: list[dict[str, str]],
    exclusions: dict[str, bool],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Use baseline catalogue resolution while preserving local recording-variant fixes."""
    from backend import youtube
    from backend.artist_quota_detection import artist_matches, quota_deficits
    from backend.candidate_context import (
        annotate_resolved_candidate_context,
        filter_resolved_recording_variants_contextual,
    )
    from backend.recording_variants import (
        active_recording_policy,
        effective_resolver_options,
        policy_with_option_exclusions,
        recording_filter_conflicts,
    )

    started_at = time.perf_counter()
    try:
        recording_policy = active_recording_policy()
        conflicts = recording_filter_conflicts(exclusions, recording_policy)
        if conflicts and not recording_policy.override_exclusions:
            raise ValueError(conflicts[0].message)
        effective_exclusions = effective_resolver_options(exclusions, recording_policy)
        resolved, unresolved = await youtube.resolve_candidates(
            candidates,
            effective_exclusions,
        )
        resolved = annotate_resolved_candidate_context(
            resolved,
            candidates,
            artist_matches=artist_matches,
        )
        validation_policy = policy_with_option_exclusions(
            effective_exclusions,
            recording_policy,
        )
        resolved, variant_rejected = filter_resolved_recording_variants_contextual(
            resolved,
            validation_policy,
        )
        unresolved.extend(variant_rejected)
        selected = _select_resolved_tracks(
            resolved,
            youtube=youtube,
            artist_matches=artist_matches,
            quota_deficits=quota_deficits,
        )
        return selected, unresolved
    finally:
        _log_stage(
            "catalogue_resolution",
            started_at,
            candidates=len(candidates),
        )


def __getattr__(name: str) -> Any:
    return getattr(_core, name)
