"""Public generation runtime with optional ReccoBeats orchestration."""

from __future__ import annotations

import logging
import time
from typing import Any

from backend import generation_runtime_core as _core
from backend.reccobeats_guidance import reccobeats_guidance
from backend.reccobeats_runtime import generate as _generate_with_reccobeats

LOGGER = logging.getLogger("playlistmuse.performance")

_ACTIVE_RESOLUTION_QUOTAS = _core._ACTIVE_RESOLUTION_QUOTAS
_ACTIVE_EXACT_ARTIST_QUOTAS = _core._ACTIVE_EXACT_ARTIST_QUOTAS
_RESOLVED_SESSION_TRACKS = _core._RESOLVED_SESSION_TRACKS
_REQUESTED_SESSION_COUNT = _core._REQUESTED_SESSION_COUNT

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
_diversity_rank = _core._diversity_rank
_log_stage = _core._log_stage
_reccobeats_replenishment_guidance = reccobeats_guidance

discover_from_anchors = _core.discover_from_anchors
discover_for_seed = _core.discover_for_seed


async def generate_playlist_draft(
    config: Any,
    prompt: str,
    count: int,
) -> dict[str, Any]:
    return await _generate_with_reccobeats(_core, config, prompt, count)


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
    from backend import youtube
    from backend.artist_quota_detection import artist_matches, quota_deficits
    from backend.recording_variants import (
        active_recording_policy,
        effective_resolver_options,
        filter_resolved_recording_variants,
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
        validation_policy = policy_with_option_exclusions(
            effective_exclusions,
            recording_policy,
        )
        resolved, variant_rejected = filter_resolved_recording_variants(
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
        recco_candidates = sum(
            1
            for candidate in candidates
            if str(candidate.get("source", "")).strip() == "reccobeats"
        )
        recco_selected = sum(
            1
            for track in selected
            if str(track.get("source", "")).strip() == "reccobeats"
        )
        LOGGER.info(
            "reccobeats_catalogue candidates=%s selected=%s recco_candidates=%s "
            "recco_selected=%s",
            len(candidates),
            len(selected),
            recco_candidates,
            recco_selected,
        )
        return selected, unresolved
    finally:
        _log_stage("catalogue_resolution", started_at, candidates=len(candidates))


def __getattr__(name: str) -> Any:
    return getattr(_core, name)
