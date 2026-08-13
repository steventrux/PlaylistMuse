"""Generation-time ReccoBeats discovery and popularity orchestration."""

from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar
from typing import Any

from backend.popularity_intent import (
    PopularityIntent,
    activate_popularity_intent,
    active_popularity_intent,
    interpret_popularity_intent,
)
from backend.reccobeats_anchors import interpret_reccobeats_anchors
from backend.reccobeats_features import recommendation_candidates_from_tracks
from backend.reccobeats_guidance import popularity_preference, reccobeats_guidance
from backend.reccobeats_popularity import (
    canonicalize_reccobeats_matches,
    enrich_recommendation_popularity,
)

LOGGER = logging.getLogger("playlistmuse.performance")
_ACTIVE_CANDIDATES: ContextVar[tuple[dict[str, Any], ...]] = ContextVar(
    "playlistmuse_reccobeats_runtime_candidates",
    default=(),
)


async def _recommend(
    anchors: list[dict[str, Any]], count: int, preference: str
) -> list[dict[str, Any]]:
    if not anchors:
        return []
    try:
        raw = await recommendation_candidates_from_tracks(
            anchors,
            limit=min(24, max(12, count)),
            max_anchors=3,
        )
        return await enrich_recommendation_popularity(
            [dict(item) for item in raw],
            preference=preference,
        )
    except Exception as error:  # noqa: BLE001 - optional discovery is fail-open.
        LOGGER.info("reccobeats_runtime unavailable error=%s", type(error).__name__)
        return []


async def generate(
    core: Any,
    config: Any,
    prompt: str,
    count: int,
) -> dict[str, Any]:
    optimized, optimized_count = core._optimized_replenishment_request(prompt, count)
    stage = core._stage_name(optimized)
    source = core._constraint_source(optimized, stage)
    candidates: list[dict[str, Any]] = []
    enhanced = prompt

    if stage in {"llm_initial", "llm_replacement"}:
        activate_popularity_intent(PopularityIntent())
        _ACTIVE_CANDIDATES.set(())

    if stage == "llm_initial":
        intent, anchors = await asyncio.gather(
            interpret_popularity_intent(config, source),
            interpret_reccobeats_anchors(config, source),
        )
        activate_popularity_intent(intent)
        anchor_tracks = [dict(item) for item in anchors if isinstance(item, dict)]
        candidates = await _recommend(
            anchor_tracks, optimized_count, popularity_preference(intent)
        )
        _ACTIVE_CANDIDATES.set(tuple(map(dict, candidates)))
        guidance = reccobeats_guidance(candidates, popularity_preference(intent))
        enhanced += guidance
        LOGGER.info(
            "reccobeats_initial anchors=%s candidates=%s applied=%s popularity=%s",
            len(anchor_tracks), len(candidates), bool(guidance), popularity_preference(intent)
        )
    elif stage == "llm_guided":
        intent = active_popularity_intent()
        candidates = [dict(item) for item in _ACTIVE_CANDIDATES.get()]
        enhanced += reccobeats_guidance(candidates, popularity_preference(intent))
    elif stage == "llm_replenishment":
        intent = active_popularity_intent()
        anchors = [
            dict(track)
            for track in core._RESOLVED_SESSION_TRACKS.get()
            if isinstance(track, dict)
        ]
        candidates = await _recommend(
            anchors, optimized_count, popularity_preference(intent)
        )
        _ACTIVE_CANDIDATES.set(tuple(map(dict, candidates)))
        guidance = reccobeats_guidance(candidates, popularity_preference(intent))
        enhanced += guidance
        LOGGER.info(
            "reccobeats_enhanced_replenishment anchors=%s candidates=%s applied=%s popularity=%s",
            len(anchors), len(candidates), bool(guidance), popularity_preference(intent)
        )
    elif stage == "llm_replacement":
        intent = await interpret_popularity_intent(config, source)
        activate_popularity_intent(intent)

    draft = await core.generate_playlist_draft(config, enhanced, count)
    tracks = [dict(item) for item in draft.get("tracks", []) if isinstance(item, dict)]
    if candidates and tracks:
        draft["tracks"] = canonicalize_reccobeats_matches(tracks, candidates)
    return draft
