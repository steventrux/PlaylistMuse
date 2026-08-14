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
from backend.popularity_policy import (
    filter_absolute_popularity,
    popularity_policy_label,
    popularity_value,
)
from backend.popularity_runtime import (
    merge_identity_locked_tracks,
    partition_absolute_popularity,
    revalidate_creative_and_policy,
)
from backend.reccobeats_anchors import interpret_reccobeats_anchors
from backend.reccobeats_features import recommendation_candidates_from_tracks
from backend.reccobeats_guidance import popularity_preference, reccobeats_guidance
from backend.reccobeats_popularity import (
    canonicalize_reccobeats_matches,
    enrich_recommendation_popularity,
    popularity_for_tracks,
)
from backend.reccobeats_selector import select_reccobeats_draft
from backend.text_normalization import normalize_identity

LOGGER = logging.getLogger("playlistmuse.performance")
POPULARITY_POOL_LIMIT = 96
POPULARITY_CONTEXT_LIMIT = 30
POPULARITY_RECOMMENDATION_SIZE = 30
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


def _popularity_value(candidate: dict[str, Any]) -> int | None:
    return popularity_value(candidate)


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
    values = [
        value
        for candidate in candidates
        if (value := _popularity_value(candidate)) is not None
    ]
    if not values:
        return 0, None, None, None
    return len(values), min(values), max(values), round(sum(values) / len(values), 1)


def _generation_count(count: int, intent: PopularityIntent, stage: str) -> int:
    """Create a bounded reserve only when popularity was explicitly requested."""
    requested = max(1, int(count))
    if stage != "llm_initial" or not intent.active or requested >= 30:
        return requested
    reserve = max(4, (requested + 4) // 5)
    return min(30, requested + reserve)


def _popularity_buffer_guidance(requested: int, generated: int) -> str:
    if generated <= requested:
        return ""
    return (
        "\n\nINTERNAL POPULARITY CANDIDATE BUFFER: return exactly "
        f"{generated} distinct, fully eligible candidate tracks. The final playlist still "
        f"contains exactly {requested}. PlaylistMuse will verify the explicit absolute "
        "Recco popularity policy before final selection. Do not relax any hard or creative "
        "requirement to fill this internal reserve."
    )


def _batch_signature(batch: list[dict[str, Any]]) -> tuple[tuple[str, str], ...]:
    return tuple(
        key
        for anchor in batch
        if all((key := _candidate_key(anchor)))
    )


def _popularity_discovery_batches(
    anchors: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Build complementary seed combinations for one bounded popularity discovery wave."""
    usable = [dict(anchor) for anchor in anchors[:6] if isinstance(anchor, dict)]
    primary = usable[:3]
    secondary = usable[3:6]
    if not primary:
        return []

    proposed: list[list[dict[str, Any]]] = [primary]
    if secondary:
        proposed.append(secondary)
        combined = [*primary, *secondary]
        odd = combined[::2][:3]
        even = combined[1::2][:3]
        if odd:
            proposed.append(odd)
        if even:
            proposed.append(even)
    else:
        proposed.extend([[anchor] for anchor in primary])

    batches: list[list[dict[str, Any]]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for batch in proposed:
        signature = _batch_signature(batch)
        if not signature or signature in seen:
            continue
        seen.add(signature)
        batches.append(batch[:3])
        if len(batches) >= 4:
            break
    return batches


def _popularity_fallback_batches(
    anchors: list[dict[str, Any]],
    existing: list[list[dict[str, Any]]],
) -> list[list[dict[str, Any]]]:
    """Recover strict seed-resolution misses without another LLM anchor call."""
    primary = [dict(anchor) for anchor in anchors[:3] if isinstance(anchor, dict)]
    secondary = [dict(anchor) for anchor in anchors[3:6] if isinstance(anchor, dict)]
    proposed: list[list[dict[str, Any]]] = [[anchor] for anchor in primary]
    if secondary:
        proposed.append(secondary)

    seen = {_batch_signature(batch) for batch in existing}
    fallback: list[list[dict[str, Any]]] = []
    for batch in proposed:
        signature = _batch_signature(batch)
        if not signature or signature in seen:
            continue
        seen.add(signature)
        fallback.append(batch)
    return fallback


async def _recommend_raw(
    anchors: list[dict[str, Any]],
    count: int,
    *,
    request_limit: int | None = None,
) -> list[dict[str, Any]]:
    if not anchors:
        return []
    limit = (
        min(POPULARITY_RECOMMENDATION_SIZE, max(1, int(request_limit)))
        if request_limit is not None
        else min(24, max(12, count))
    )
    try:
        raw = await recommendation_candidates_from_tracks(
            anchors,
            limit=limit,
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


async def _enriched_absolute_pool(
    raw_results: list[list[dict[str, Any]]],
    preference: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    merged = _merge_recommendations(raw_results, limit=POPULARITY_POOL_LIMIT)
    enriched = await enrich_recommendation_popularity(
        merged,
        preference=preference,
    )
    return enriched, filter_absolute_popularity(enriched, preference)


async def _recommend_popularity_pool(
    anchors: list[dict[str, Any]],
    count: int,
    preference: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build a broad pool, enforce an absolute band, then expose immutable candidates."""
    batches = _popularity_discovery_batches(anchors)
    metadata: dict[str, Any] = {
        "anchor_count": len(anchors),
        "primary_anchor_count": min(3, len(anchors)),
        "secondary_anchor_count": min(3, max(0, len(anchors) - 3)),
        "primary_candidates": 0,
        "fallback_used": False,
        "fallback_candidates": 0,
        "fallback_result_counts": (),
        "expanded_pool": True,
        "discovery_batches": len(batches),
        "batch_result_counts": (),
        "pool_candidates": 0,
        "context_candidates": 0,
        "absolute_policy": popularity_policy_label(preference),
        "absolute_candidates": 0,
    }
    if not batches:
        return [], metadata

    raw_results = await asyncio.gather(
        *(
            _recommend_raw(
                batch,
                count,
                request_limit=POPULARITY_RECOMMENDATION_SIZE,
            )
            for batch in batches
        )
    )
    raw_results = [list(result) for result in raw_results]
    metadata["primary_candidates"] = len(raw_results[0]) if raw_results else 0
    metadata["batch_result_counts"] = tuple(len(result) for result in raw_results)

    enriched, absolute = await _enriched_absolute_pool(raw_results, preference)
    target = min(POPULARITY_CONTEXT_LIMIT, max(12, int(count)))
    fallback_batches = _popularity_fallback_batches(anchors, batches)
    if len(absolute) < target and fallback_batches:
        fallback_results = await asyncio.gather(
            *(
                _recommend_raw(
                    batch,
                    count,
                    request_limit=POPULARITY_RECOMMENDATION_SIZE,
                )
                for batch in fallback_batches
            )
        )
        fallback_results = [list(result) for result in fallback_results]
        raw_results.extend(fallback_results)
        metadata["fallback_used"] = True
        metadata["fallback_result_counts"] = tuple(
            len(result) for result in fallback_results
        )
        metadata["fallback_candidates"] = sum(
            len(result) for result in fallback_results
        )
        metadata["discovery_batches"] += len(fallback_batches)
        metadata["batch_result_counts"] = (
            *metadata["batch_result_counts"],
            *(len(result) for result in fallback_results),
        )
        enriched, absolute = await _enriched_absolute_pool(raw_results, preference)

    context = absolute[:POPULARITY_CONTEXT_LIMIT]
    known, minimum, maximum, average = _popularity_summary(enriched)
    absolute_known, absolute_min, absolute_max, absolute_avg = _popularity_summary(absolute)
    context_known, context_min, context_max, context_avg = _popularity_summary(context)
    metadata.update(
        {
            "pool_candidates": len(enriched),
            "pool_popularity_known": known,
            "pool_popularity_min": minimum,
            "pool_popularity_max": maximum,
            "pool_popularity_avg": average,
            "absolute_candidates": len(absolute),
            "absolute_popularity_known": absolute_known,
            "absolute_popularity_min": absolute_min,
            "absolute_popularity_max": absolute_max,
            "absolute_popularity_avg": absolute_avg,
            "context_candidates": len(context),
            "context_popularity_known": context_known,
            "context_popularity_min": context_min,
            "context_popularity_max": context_max,
            "context_popularity_avg": context_avg,
        }
    )
    return context, metadata


async def _recommend_with_fallback(
    anchors: list[dict[str, Any]],
    count: int,
    preference: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Use absolute popularity discovery when requested; retain neutral fallback behavior."""
    normalized = str(preference).strip().casefold()
    if normalized in {"popular", "less_known"}:
        return await _recommend_popularity_pool(
            anchors,
            count,
            normalized,
        )

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
        "expanded_pool": False,
        "discovery_batches": 1 if primary else 0,
        "batch_result_counts": (len(primary_raw),) if primary else (),
        "pool_candidates": len(primary_raw),
        "context_candidates": len(primary_raw),
        "absolute_policy": "neutral",
        "absolute_candidates": len(primary_raw),
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
    merged = _merge_recommendations(list(raw_results), limit=limit)
    metadata["fallback_used"] = True
    metadata["fallback_candidates"] = len(merged)
    metadata["fallback_result_counts"] = tuple(len(result) for result in raw_results)
    metadata["discovery_batches"] = 1 + len(fallback_batches)
    metadata["batch_result_counts"] = (0, *(len(result) for result in raw_results))
    metadata["pool_candidates"] = len(merged)
    metadata["context_candidates"] = len(merged)
    metadata["absolute_candidates"] = len(merged)
    return (
        await enrich_recommendation_popularity(merged, preference=preference),
        metadata,
    )


async def _score_and_rank_tracks(
    tracks: list[dict[str, Any]],
    intent: PopularityIntent,
) -> list[dict[str, Any]]:
    """Attach Recco popularity to free-form LLM fallback identities and rank them."""
    copied = [dict(track) for track in tracks]
    if not copied or not intent.active:
        return copied

    known_scores = {
        _candidate_key(track): score
        for track in copied
        if (score := _popularity_value(track)) is not None
        and all(_candidate_key(track))
    }
    missing = [track for track in copied if _candidate_key(track) not in known_scores]
    if missing:
        fetched = await popularity_for_tracks(missing)
        known_scores.update(fetched)

    for track in copied:
        score = known_scores.get(_candidate_key(track))
        if score is not None:
            track["popularity"] = score

    preference = popularity_preference(intent)

    def key(track: dict[str, Any]) -> tuple[int, int]:
        score = _popularity_value(track)
        if score is None:
            return 1, 0
        return 0, -score if preference == "popular" else score

    return sorted(copied, key=key)


def _log_discovery_stats(
    *,
    stage: str,
    preference: str,
    anchors: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    metadata: dict[str, Any],
    draft_tracks: list[dict[str, Any]],
    selector_tracks: int = 0,
    popularity_rejected: int = 0,
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
    draft_known, draft_min, draft_max, draft_avg = _popularity_summary(draft_tracks)
    LOGGER.info(
        "reccobeats_stats stage=%s popularity=%s absolute_policy=%s anchors=%s "
        "expanded_pool=%s discovery_batches=%s batch_result_counts=%s "
        "primary_candidates=%s fallback_used=%s fallback_candidates=%s "
        "pool_candidates=%s absolute_candidates=%s pool_popularity_known=%s "
        "pool_popularity_min=%s pool_popularity_max=%s pool_popularity_avg=%s "
        "candidates=%s popularity_known=%s popularity_min=%s popularity_max=%s "
        "popularity_avg=%s draft_tracks=%s draft_popularity_known=%s "
        "draft_popularity_min=%s draft_popularity_max=%s draft_popularity_avg=%s "
        "draft_recco=%s draft_recco_popularity_known=%s draft_recco_popularity_min=%s "
        "draft_recco_popularity_max=%s draft_recco_popularity_avg=%s "
        "selector_tracks=%s popularity_rejected=%s",
        stage,
        preference,
        metadata.get("absolute_policy", popularity_policy_label(preference)),
        len(anchors),
        metadata.get("expanded_pool", False),
        metadata.get("discovery_batches", 0),
        metadata.get("batch_result_counts", ()),
        metadata.get("primary_candidates", 0),
        metadata.get("fallback_used", False),
        metadata.get("fallback_candidates", 0),
        metadata.get("pool_candidates", len(candidates)),
        metadata.get("absolute_candidates", len(candidates)),
        metadata.get("pool_popularity_known", known),
        metadata.get("pool_popularity_min", minimum),
        metadata.get("pool_popularity_max", maximum),
        metadata.get("pool_popularity_avg", average),
        len(candidates),
        known,
        minimum,
        maximum,
        average,
        len(draft_tracks),
        draft_known,
        draft_min,
        draft_max,
        draft_avg,
        len(recco_tracks),
        selected_known,
        selected_min,
        selected_max,
        selected_avg,
        selector_tracks,
        popularity_rejected,
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
        generated_count = _generation_count(count, intent, stage)
        guidance += _popularity_buffer_guidance(count, generated_count)
        enhanced = _add_guidance(prompt, guidance, stage)
        LOGGER.info(
            "reccobeats_initial anchors=%s candidates=%s pool_candidates=%s applied=%s "
            "popularity=%s absolute_policy=%s expanded_pool=%s requested=%s generated=%s",
            len(discovery_anchors),
            len(candidates),
            discovery_metadata.get("pool_candidates", len(candidates)),
            bool(guidance),
            popularity_preference(intent),
            discovery_metadata.get("absolute_policy", popularity_policy_label(intent.preference)),
            discovery_metadata.get("expanded_pool", False),
            count,
            generated_count,
        )
        LOGGER.info(
            "popularity_intent stage=%s preference=%s confidence=%.2f active=%s",
            stage,
            intent.preference,
            intent.confidence,
            intent.active,
        )
    else:
        intent = active_popularity_intent()
        generated_count = count

    if stage == "llm_guided":
        candidates = [dict(item) for item in _ACTIVE_CANDIDATES.get()]
        enhanced = _add_guidance(
            prompt,
            reccobeats_guidance(candidates, popularity_preference(intent)),
            stage,
        )
    elif stage == "llm_replenishment":
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
            "reccobeats_enhanced_replenishment anchors=%s candidates=%s pool_candidates=%s "
            "applied=%s popularity=%s absolute_policy=%s expanded_pool=%s",
            len(discovery_anchors),
            len(candidates),
            discovery_metadata.get("pool_candidates", len(candidates)),
            bool(guidance),
            popularity_preference(intent),
            discovery_metadata.get("absolute_policy", popularity_policy_label(intent.preference)),
            discovery_metadata.get("expanded_pool", False),
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

    session_token = None
    if stage == "llm_replenishment":
        # The outer runtime already performed Recco discovery. Hide the resolved session only
        # during the legacy nested discovery block so it cannot issue a duplicate Recco call.
        session_token = core._RESOLVED_SESSION_TRACKS.set(())
    try:
        draft = await core.generate_playlist_draft(
            config,
            enhanced,
            generated_count,
        )
    finally:
        if session_token is not None:
            core._RESOLVED_SESSION_TRACKS.reset(session_token)

    if stage == "llm_initial" and generated_count != count:
        # Candidate buffering must never change the final requested playlist capacity.
        core._REQUESTED_SESSION_COUNT.set(max(0, int(count)))

    tracks = [dict(item) for item in draft.get("tracks", []) if isinstance(item, dict)]
    if candidates and tracks:
        tracks = canonicalize_reccobeats_matches(tracks, candidates)
    tracks = await _score_and_rank_tracks(tracks, active_popularity_intent())

    selector_tracks = 0
    popularity_rejected: list[dict[str, Any]] = []
    active_intent = active_popularity_intent()
    preference = popularity_preference(active_intent)
    if active_intent.active:
        fallback_tracks, popularity_rejected = partition_absolute_popularity(
            tracks,
            preference,
        )
        selection_target = (
            optimized_count if stage == "llm_replenishment" else generated_count
        )
        locked_draft = None
        if candidates and stage in {"llm_initial", "llm_replenishment"}:
            locked_draft = await select_reccobeats_draft(
                config,
                source,
                candidates,
                count=selection_target,
                preference=preference,
            )
        if locked_draft is not None:
            locked_tracks = [
                dict(item)
                for item in locked_draft.get("tracks", [])
                if isinstance(item, dict)
            ]
            selector_tracks = len(locked_tracks)
            merged = merge_identity_locked_tracks(
                locked_tracks,
                fallback_tracks,
                limit=selection_target,
            )
            draft["tracks"] = merged
            draft = await revalidate_creative_and_policy(
                config,
                draft,
                requested_count=selection_target,
            )
            tracks = [
                dict(item)
                for item in draft.get("tracks", [])
                if isinstance(item, dict)
            ]
        else:
            tracks = fallback_tracks
            draft["tracks"] = tracks

        if popularity_rejected:
            draft["popularity_rejected"] = popularity_rejected
        LOGGER.info(
            "popularity_enforcement stage=%s preference=%s policy=%s input=%s "
            "selector_tracks=%s accepted=%s rejected=%s",
            stage,
            preference,
            popularity_policy_label(preference),
            len(tracks) + len(popularity_rejected),
            selector_tracks,
            len(tracks),
            len(popularity_rejected),
        )
    else:
        draft["tracks"] = tracks

    if stage in {"llm_initial", "llm_replenishment"}:
        _log_discovery_stats(
            stage=stage,
            preference=preference,
            anchors=discovery_anchors,
            candidates=candidates,
            metadata=discovery_metadata,
            draft_tracks=tracks,
            selector_tracks=selector_tracks,
            popularity_rejected=len(popularity_rejected),
        )
    return draft
