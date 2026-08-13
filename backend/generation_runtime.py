"""Request-scoped generation runtime with ReccoBeats discovery orchestration."""

from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar
from typing import Any

from backend import generation_runtime_core as _core
from backend.popularity_intent import (
    PopularityIntent,
    activate_popularity_intent,
    active_popularity_intent,
    interpret_popularity_intent,
)
from backend.reccobeats_anchors import interpret_reccobeats_anchors
from backend.reccobeats_features import recommendation_candidates_from_tracks
from backend.reccobeats_popularity import (
    canonicalize_reccobeats_matches,
    enrich_recommendation_popularity,
)

logger = logging.getLogger("playlistmuse.performance")

# Re-export the request-scoped state used by catalogue selection and existing callers.
_ACTIVE_RESOLUTION_QUOTAS = _core._ACTIVE_RESOLUTION_QUOTAS
_ACTIVE_EXACT_ARTIST_QUOTAS = _core._ACTIVE_EXACT_ARTIST_QUOTAS
_RESOLVED_SESSION_TRACKS = _core._RESOLVED_SESSION_TRACKS
_REQUESTED_SESSION_COUNT = _core._REQUESTED_SESSION_COUNT

# Preserve the established helper surface.
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
_select_resolved_tracks = _core._select_resolved_tracks

discover_from_anchors = _core.discover_from_anchors
discover_for_seed = _core.discover_for_seed
resolve_candidates = _core.resolve_candidates

_ACTIVE_RECCOBEATS_CANDIDATES: ContextVar[tuple[dict[str, Any], ...]] = ContextVar(
    "playlistmuse_reccobeats_candidates",
    default=(),
)


def _popularity_preference() -> str:
    intent = active_popularity_intent()
    return intent.preference if intent.active else "neutral"


def _candidate_line(candidate: dict[str, Any]) -> str:
    artist = str(candidate.get("artist", "Unknown artist"))
    title = str(candidate.get("title", "Unknown track"))
    popularity = candidate.get("popularity")
    suffix = f" [Recco popularity: {popularity}]" if popularity is not None else ""
    return f"- {artist} — {title}{suffix}"


def _reccobeats_replenishment_guidance(
    candidates: list[dict[str, Any]],
    popularity_preference: str = "neutral",
) -> str:
    """Expose verified Recco identities and optional relative popularity evidence."""
    usable = [
        candidate
        for candidate in candidates[:24]
        if str(candidate.get("artist", "")).strip()
        and str(candidate.get("title", "")).strip()
    ]
    if not usable:
        return ""

    preference = str(popularity_preference).strip().casefold()
    popularity_rule = ""
    if preference == "popular":
        popularity_rule = (
            " The user explicitly prefers more popular or recognizable songs. Among "
            "otherwise equally compliant candidates, prefer higher Recco popularity values."
        )
    elif preference == "less_known":
        popularity_rule = (
            " The user explicitly prefers lesser-known songs. Among otherwise equally "
            "compliant candidates, prefer lower known Recco popularity values. A missing "
            "popularity value is neutral and must not be treated as proof of obscurity."
        )

    return (
        "\n\nRECCOBEATS DISCOVERY: the following catalogue-backed recommendations are "
        "real ReccoBeats identities. If you select one of them, copy its artist and title "
        "exactly as written; do not rewrite, translate or reattribute the identity. They are "
        "discovery candidates, not pre-approved selections: every hard constraint, artist "
        "quota, recording-version rule, creative requirement and forbidden/already-attempted "
        "list remains authoritative. Never include a song only because it appears in this "
        "pool. Popularity is always a soft preference and never overrides eligibility or "
        "creative fit."
        f"{popularity_rule}\n"
        + "\n".join(_candidate_line(candidate) for candidate in usable)
    )


def _initial_reccobeats_guidance(
    candidates: list[dict[str, Any]],
    popularity_preference: str,
) -> str:
    guidance = _reccobeats_replenishment_guidance(
        candidates,
        popularity_preference,
    )
    if not guidance:
        return ""
    return guidance.replace(
        "derived from tracks already verified in this playlist. ",
        "",
    )


async def _recommendations_from_anchors(
    anchors: list[dict[str, Any]],
    *,
    limit: int,
    preference: str,
) -> list[dict[str, Any]]:
    if not anchors:
        return []
    try:
        candidates = await recommendation_candidates_from_tracks(
            anchors,
            limit=limit,
            max_anchors=3,
        )
        return await enrich_recommendation_popularity(
            [dict(candidate) for candidate in candidates],
            preference=preference,
        )
    except Exception as error:  # noqa: BLE001 - optional discovery is fail-open.
        logger.info(
            "reccobeats_discovery unavailable anchors=%s error=%s",
            len(anchors),
            type(error).__name__,
        )
        return []


async def _initial_discovery(
    config: Any,
    source_prompt: str,
    count: int,
) -> tuple[PopularityIntent, list[dict[str, Any]], list[dict[str, Any]]]:
    popularity_result, anchors_result = await asyncio.gather(
        interpret_popularity_intent(config, source_prompt),
        interpret_reccobeats_anchors(config, source_prompt),
    )
    intent = (
        popularity_result
        if isinstance(popularity_result, PopularityIntent)
        else PopularityIntent(confidence=0.0)
    )
    anchors = [dict(anchor) for anchor in anchors_result if isinstance(anchor, dict)]
    preference = intent.preference if intent.active else "neutral"
    candidates = await _recommendations_from_anchors(
        anchors,
        limit=min(24, max(12, int(count))),
        preference=preference,
    )
    return intent, anchors, candidates


async def generate_playlist_draft(
    config: Any,
    prompt: str,
    count: int,
) -> dict[str, Any]:
    """Generate one draft while adding fail-open Recco discovery before the main LLM call."""
    optimized_prompt, optimized_count = _optimized_replenishment_request(prompt, count)
    stage = _stage_name(optimized_prompt)
    source_prompt = _constraint_source(optimized_prompt, stage)

    reccobeats_candidates: list[dict[str, Any]] = []
    discovery_anchors: list[dict[str, Any]] = []
    enhanced_prompt = prompt

    if stage in {"llm_initial", "llm_replacement"}:
        activate_popularity_intent(PopularityIntent())
        _ACTIVE_RECCOBEATS_CANDIDATES.set(())

    if stage == "llm_initial":
        popularity_intent, discovery_anchors, reccobeats_candidates = (
            await _initial_discovery(config, source_prompt, optimized_count)
        )
        activate_popularity_intent(popularity_intent)
        _ACTIVE_RECCOBEATS_CANDIDATES.set(
            tuple(dict(candidate) for candidate in reccobeats_candidates)
        )
        guidance = _initial_reccobeats_guidance(
            reccobeats_candidates,
            _popularity_preference(),
        )
        if guidance:
            enhanced_prompt += guidance
        logger.info(
            "reccobeats_initial anchors=%s candidates=%s applied=%s popularity=%s",
            len(discovery_anchors),
            len(reccobeats_candidates),
            bool(guidance),
            _popularity_preference(),
        )
        logger.info(
            "popularity_intent stage=%s preference=%s confidence=%.2f active=%s",
            stage,
            popularity_intent.preference,
            popularity_intent.confidence,
            popularity_intent.active,
        )
    elif stage == "llm_guided":
        reccobeats_candidates = [
            dict(candidate) for candidate in _ACTIVE_RECCOBEATS_CANDIDATES.get()
        ]
        guidance = _initial_reccobeats_guidance(
            reccobeats_candidates,
            _popularity_preference(),
        )
        if guidance:
            enhanced_prompt += guidance
    elif stage == "llm_replenishment":
        discovery_anchors = [
            dict(track)
            for track in _RESOLVED_SESSION_TRACKS.get()
            if isinstance(track, dict)
        ]
        reccobeats_candidates = await _recommendations_from_anchors(
            discovery_anchors,
            limit=min(24, max(12, optimized_count)),
            preference=_popularity_preference(),
        )
        _ACTIVE_RECCOBEATS_CANDIDATES.set(
            tuple(dict(candidate) for candidate in reccobeats_candidates)
        )
        # Core already supplies the identity list during replenishment. Add only the richer
        # popularity/identity instruction here; its recommendation lookup is cache-backed.
        guidance = _reccobeats_replenishment_guidance(
            reccobeats_candidates,
            _popularity_preference(),
        )
        if guidance:
            enhanced_prompt += guidance
        logger.info(
            "reccobeats_enhanced_replenishment anchors=%s candidates=%s applied=%s popularity=%s",
            len(discovery_anchors),
            len(reccobeats_candidates),
            bool(guidance),
            _popularity_preference(),
        )
    elif stage == "llm_replacement":
        popularity_intent = await interpret_popularity_intent(config, source_prompt)
        activate_popularity_intent(popularity_intent)
        logger.info(
            "popularity_intent stage=%s preference=%s confidence=%.2f active=%s",
            stage,
            popularity_intent.preference,
            popularity_intent.confidence,
            popularity_intent.active,
        )

    draft = await _core.generate_playlist_draft(config, enhanced_prompt, count)
    tracks = [
        dict(track)
        for track in draft.get("tracks", [])
        if isinstance(track, dict)
    ]
    if reccobeats_candidates and tracks:
        draft["tracks"] = canonicalize_reccobeats_matches(
            tracks,
            reccobeats_candidates,
        )
    return draft


def __getattr__(name: str) -> Any:
    """Delegate less-common private helpers to the stable runtime implementation."""
    return getattr(_core, name)
