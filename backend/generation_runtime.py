"""Public generation runtime using the proven low-latency orchestration path."""

from __future__ import annotations

from typing import Any

from backend import generation_runtime_core as _core

# Keep the public/runtime symbols stable while routing generation through the
# pre-advanced-Recco orchestration that was measured around 60–70 seconds.
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
_reccobeats_replenishment_guidance = _core._reccobeats_replenishment_guidance

discover_from_anchors = _core.discover_from_anchors
discover_for_seed = _core.discover_for_seed


async def generate_playlist_draft(
    config: Any,
    prompt: str,
    count: int,
) -> dict[str, Any]:
    """Generate with the proven baseline path; advanced Recco orchestration is disabled."""
    return await _core.generate_playlist_draft(config, prompt, count)


async def resolve_candidates(
    candidates: list[dict[str, str]],
    exclusions: dict[str, bool],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve candidates with the baseline catalogue path."""
    return await _core.resolve_candidates(candidates, exclusions)


def _select_resolved_tracks(
    resolved: list[dict[str, Any]],
    *,
    youtube: Any,
    artist_matches: Any,
    quota_deficits: Any,
) -> list[dict[str, Any]]:
    return _core._select_resolved_tracks(
        resolved,
        youtube=youtube,
        artist_matches=artist_matches,
        quota_deficits=quota_deficits,
    )


def __getattr__(name: str) -> Any:
    return getattr(_core, name)
