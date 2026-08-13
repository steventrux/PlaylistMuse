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
from backend.text_normalization import normalize_identity

LOGGER = logging.getLogger("playlistmuse.performance")
_ACTIVE_CANDIDATES: ContextVar[tuple[dict[str, Any], ...]] = ContextVar(
    "playlistmuse_reccobeats_runtime_candidates",
    default=(),
)


def _add_guidance(prompt: str, guidance: str, stage: str) -> str:
    if not guidance:
        return prompt
    if stage == "llm_initial":
        marker = "\n\nUser request:\n"
        if marker in prompt:
            return prompt.replace(marker, guidance + marker, 1)
        return guidance + "\n\nUser request:\n" + prompt
    return prompt + guidance


def _anchor_label(anchor: dict[str, Any]) -> str:
    artist = " ".join(str(anchor.get("artist") or anchor.get("artists") or "").split())
    title = " ".join(str(anchor.get("title") or "").split())
    return f"{artist} — {title}" if artist and title else "invalid-anchor"


def _candidate_key(candidate: dict[str, Any]) -> tuple[str, str]:
    artist = str(candidate.get("artist") or candidate.get("artists") or "")
    title = str(candidate.get("title") or "")
    return normalize_identity(artist), normalize_identity(title)


def _merge_recommendations(
    batches: list[list[dict[str, Any]]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_tracks: set[tuple[str, str]] = set()
    for batch in batches:
        for candidate in batch:
            recco_id = str(candidate.get("reccobeats_id", "")).strip()
            key = _candidate_key(candidate)
            if recco_id and recco_id in seen_ids:
                continue
            if all(key) and key in seen_tracks:
                continue
            if recco_id:
                seen_ids.add(recco_id)
            if all(key):
                seen_tracks.add(key)
            merged.append(dict(candidate))
            if len(merged) >= limit:
                return merged
    return merged


def _popularity_summary(
    candidates: list[dict[str, Any]],
) -> tuple[int, int | None, int | None, float | None]:
    values: list[int] = []
    for candidate in candidates:
        value = candidate.get("popularity")
        if isinstance(value, bool):
            continue
        try:
            values.append(int(value))
        except (TypeError, ValueError):
            continue
    if not values:
        return 0, None, None, None
    return len(values), min(values), max(values), round(sum(values) / len(values), 1)


async def _recommend_raw(
    anchors: list[dict[str, Any]],
    count: int,
) -> list[dict[str, Any]]:
    if not anchors:
        return []
    try:
        raw = await recommendation_candidates_from_tracks(
            anchors,
            limit=min(24, max(12, count)),
            max_anchors=3,
        )
        return [dict(item) for item in raw]
    except Exception as error:  # noqa: BLE001 - optional discovery is fail-open.
        LOGGER.info(
            "reccobeats_runtime unavailable anchors=%s error=%s",
            len(anchors),
            type(error).__name__,
        )
        return []


async def _recommend_with_fallback(
    anchors: list[dict[str, Any]],
    count: int,
    preference: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Try primary seeds, then one bounded fallback wave when discovery returns nothing."""
    limit = min(24, max(12, count))
    primary = [dict(anchor) for anchor in anchors[:3]]
    secondary = [dict(anchor) for anchor in anchors[3:6]]
    primary_raw = await _recommend_raw(primary, count)
    metadata: dict[str, Any] = {
        "anchor_count": len(anchors),
        "primary_anchor_count": len(primary),
        "secondary_anchor_count": len(secondary),
        "primary_candidates": len(primary_raw),
        "fallback_used": False,
        "fallback_candidates": 0,
        "fallback_result_counts": (),
    }
    if primary_raw:
        return (
            await enrich_recommendation_popularity(primary_raw, preference=preference),
            metadata,
        )

    fallback_batches: list[list[dict[str, Any]]] = [[anchor] for anchor in primary]
    if secondary:
        fallback_batches.append(secondary)
    if not fallback_batches:
        return [], metadata

    raw_results = await asyncio.gather(
        *(_recommend_raw(batch, count) for batch in fallback_batches)
    )
    merged = _merge_recommendations(raw_results, limit=limit)
    metadata["fallback_used"] = True
    metadata["fallback_candidates"] = len(merged)
    metadata["fallback_result_counts"] = tuple(len(result) for result in raw_results)
    return (
        await enrich_recommendation_popularity(merged, preference=preference),
        metadata,
    )


def _log_discovery_stats(
    *,
    stage: str,
    preference: str,
    anchors: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    metadata: dict[str, Any],
    draft_tracks: list[dict[str, Any]],
) -> None:
    known, minimum, maximum, average = _popularity_summary(candidates)
    recco_tracks = [
        track
        for track in draft_tracks
        if str(track.get("source", "")).strip() == "reccobeats"
    ]
    selected_known, selected_min, selected_max, selected_avg = _popularity_summary(
        recco_tracks
    )
    LOGGER.info(
        "reccobeats_stats stage=%s popularity=%s anchors=%s primary_candidates=%s "
        "fallback_used=%s fallback_candidates=%s candidates=%s popularity_known=%s "
        "popularity_min=%s popularity_max=%s popularity_avg=%s draft_tracks=%s "
        "draft_recco=%s draft_recco_popularity_known=%s draft_recco_popularity_min=%s "
        "draft_recco_popularity_max=%s draft_recco_popularity_avg=%s",
        stage,
        preference,
        len(anchors),
        metadata.get("primary_candidates", 0),
        metadata.get("fallback_used", False),
        metadata.get("fallback_candidates", 0),
        len(candidates),
        known,
        minimum,
        maximum,
        average,
        len(draft_tracks),
        len(recco_tracks),
        selected_known,
        selected_min,
        selected_max,
        selected_avg,
    )
    if metadata.get("fallback_used"):
        LOGGER.info(
            "reccobeats_anchor_fallback stage=%s primary=%s secondary=%s result_counts=%s",
            stage,
            " | ".join(_anchor_label(anchor) for anchor in anchors[:3]) or "none",
            " | ".join(_anchor_label(anchor) for anchor in anchors[3:6]) or "none",
            metadata.get("fallback_result_counts", ()),
        )


async def generate(core: Any, config: Any, prompt: str, count: int) -> dict[str, Any]:
    optimized, optimized_count = core._optimized_replenishment_request(prompt, count)
    stage = core._stage_name(optimized)
    source = core._constraint_source(optimized, stage)
    candidates: list[dict[str, Any]] = []
    discovery_anchors: list[dict[str, Any]] = []
    discovery_metadata: dict[str, Any] = {}
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
        discovery_anchors = [dict(item) for item in anchors if isinstance(item, dict)]
        candidates, discovery_metadata = await _recommend_with_fallback(
            discovery_anchors,
            optimized_count,
            popularity_preference(intent),
        )
        _ACTIVE_CANDIDATES.set(tuple(map(dict, candidates)))
        guidance = reccobeats_guidance(candidates, popularity_preference(intent))
        enhanced = _add_guidance(prompt, guidance, stage)
        LOGGER.info(
            "reccobeats_initial anchors=%s candidates=%s applied=%s popularity=%s fallback=%s",
            len(discovery_anchors),
            len(candidates),
            bool(guidance),
            popularity_preference(intent),
            discovery_metadata.get("fallback_used", False),
        )
        LOGGER.info(
            "popularity_intent stage=%s preference=%s confidence=%.2f active=%s",
            stage,
            intent.preference,
            intent.confidence,
            intent.active,
        )
    elif stage == "llm_guided":
        intent = active_popularity_intent()
        candidates = [dict(item) for item in _ACTIVE_CANDIDATES.get()]
        enhanced = _add_guidance(
            prompt,
            reccobeats_guidance(candidates, popularity_preference(intent)),
            stage,
        )
    elif stage == "llm_replenishment":
        intent = active_popularity_intent()
        discovery_anchors = [
            dict(track)
            for track in core._RESOLVED_SESSION_TRACKS.get()
            if isinstance(track, dict)
        ]
        candidates, discovery_metadata = await _recommend_with_fallback(
            discovery_anchors,
            optimized_count,
            popularity_preference(intent),
        )
        _ACTIVE_CANDIDATES.set(tuple(map(dict, candidates)))
        guidance = reccobeats_guidance(candidates, popularity_preference(intent))
        enhanced = _add_guidance(prompt, guidance, stage)
        LOGGER.info(
            "reccobeats_enhanced_replenishment anchors=%s candidates=%s applied=%s "
            "popularity=%s fallback=%s",
            len(discovery_anchors),
            len(candidates),
            bool(guidance),
            popularity_preference(intent),
            discovery_metadata.get("fallback_used", False),
        )
    elif stage == "llm_replacement":
        intent = await interpret_popularity_intent(config, source)
        activate_popularity_intent(intent)
        LOGGER.info(
            "popularity_intent stage=%s preference=%s confidence=%.2f active=%s",
            stage,
            intent.preference,
            intent.confidence,
            intent.active,
        )

    draft = await core.generate_playlist_draft(config, enhanced, count)
    tracks = [dict(item) for item in draft.get("tracks", []) if isinstance(item, dict)]
    if candidates and tracks:
        draft["tracks"] = canonicalize_reccobeats_matches(tracks, candidates)
        tracks = [dict(item) for item in draft["tracks"] if isinstance(item, dict)]

    if stage in {"llm_initial", "llm_replenishment"}:
        _log_discovery_stats(
            stage=stage,
            preference=popularity_preference(active_popularity_intent()),
            anchors=discovery_anchors,
            candidates=candidates,
            metadata=discovery_metadata,
            draft_tracks=tracks,
        )
    return draft