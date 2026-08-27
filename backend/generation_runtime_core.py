"""Explicit request-scoped generation orchestration and catalogue selection."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from contextvars import ContextVar
from dataclasses import asdict
from typing import Any

from backend.generation_stage_timing import record_stage_ms

logger = logging.getLogger("playlistmuse.performance")

MAX_CREATIVE_REPAIR_ROUNDS = 1
INITIAL_ANCHOR_TIMEOUT_SECONDS = 6.0

_REPLENISHMENT_MISSING_RE = re.compile(
    r"still needs\s+(\d+)\s+resolvable songs", re.IGNORECASE
)
_REPLENISHMENT_COUNT_RE = re.compile(
    r"Suggest exactly\s+\d+\s+NEW", re.IGNORECASE
)
_STRICT_MAJORITY_ARTIST_RE = re.compile(
    r"\bpi[uù]\s+della\s+met[aà]\s+(?:dei|degli|delle)?\s*"
    r"(?:brani|canzoni|tracce|pezzi)?\s*(?:deve|devono)?\s*"
    r"(?:essere|provenire)?\s*(?:di|dei|degli|delle)\s+([^,;.!\n]{1,120})",
    re.IGNORECASE,
)

_ACTIVE_RESOLUTION_QUOTAS: ContextVar[tuple[Any, ...]] = ContextVar(
    "playlistmuse_resolution_quotas", default=()
)
_ACTIVE_EXACT_ARTIST_QUOTAS: ContextVar[tuple[Any, ...]] = ContextVar(
    "playlistmuse_exact_artist_quotas", default=()
)
_RESOLVED_SESSION_TRACKS: ContextVar[tuple[dict[str, Any], ...]] = ContextVar(
    "playlistmuse_resolved_session_tracks", default=()
)
_REQUESTED_SESSION_COUNT: ContextVar[int] = ContextVar(
    "playlistmuse_requested_session_count", default=0
)
_LAST_INTERPRETED_CONSTRAINTS: ContextVar[dict[str, Any] | None] = ContextVar(
    "playlistmuse_last_interpreted_constraints", default=None
)
_TASTE_MEMORY_SIGNAL: ContextVar[dict[str, list[str]] | None] = ContextVar(
    "playlistmuse_taste_memory_signal", default=None
)


def activate_taste_memory_signal(signal: dict[str, list[str]] | None) -> None:
    _TASTE_MEMORY_SIGNAL.set(signal)


def active_taste_memory_signal() -> dict[str, list[str]] | None:
    return _TASTE_MEMORY_SIGNAL.get()


def _stage_name(prompt: str) -> str:
    normalized = prompt.lstrip()
    if normalized.startswith("The original playlist request is:"):
        return "llm_replenishment"
    if normalized.startswith("Create the final playlist for this request:"):
        return "llm_guided"
    if normalized.startswith("Suggest exactly 6 strong replacement candidates"):
        return "llm_replacement"
    return "llm_initial"


def _creative_repair_rounds(stage: str) -> int:
    """Avoid regenerating refill pools; one repair is enough for full drafts."""
    return 0 if stage == "llm_replenishment" else MAX_CREATIVE_REPAIR_ROUNDS


def _constraint_source(prompt: str, stage: str) -> str:
    """Extract only the original user request from internal instructions."""
    if "User request:\n" in prompt:
        return prompt.split("User request:\n", 1)[1].strip()
    if stage == "llm_replacement" and "Original playlist request:" in prompt:
        tail = prompt.split("Original playlist request:", 1)[1]
        return tail.split("\n", 1)[0].strip()
    return prompt.strip()


def _quota_replenishment_guidance(prompt: str) -> str:
    if not prompt.lstrip().startswith("The original playlist request is:"):
        return ""
    request = prompt.split("The original playlist request is:\n", 1)[1].split(
        "\n", 1
    )[0]
    match = _STRICT_MAJORITY_ARTIST_RE.search(request)
    if not match:
        return ""
    artist = " ".join(match.group(1).split()).strip(" .,-")
    if not artist:
        return ""
    return (
        "\n\nQUOTA REPLENISHMENT: the original request requires a strict majority of "
        f"tracks by {artist}. Prioritize distinct, normal studio tracks by {artist} that "
        "also satisfy every era, genre and exclusion constraint. At least three quarters "
        "of the replacement candidates in this round should be by that artist until the "
        "playlist can satisfy the requested majority. Do not repeat previously attempted songs."
    )


def _numeric_quota_replenishment_guidance(prompt: str, pool_size: int) -> str:
    """Request independent reserves for every explicit numeric artist quota."""
    if not prompt.lstrip().startswith("The original playlist request is:"):
        return ""

    from backend.artist_quota_detection import extract_artist_minimum_quotas

    quotas = extract_artist_minimum_quotas(prompt)
    if not quotas:
        return ""

    per_artist = max(6, min(10, pool_size // max(1, len(quotas))))
    requirements = "; ".join(
        f"at least {per_artist} distinct candidates by {quota.artist}"
        for quota in quotas
    )
    return (
        "\n\nNUMERIC QUOTA REPLENISHMENT: catalogue resolution may reject or deduplicate "
        "some suggestions, so provide a generous independent reserve for every quota "
        f"artist in this round: {requirements}. Use normal studio recordings with canonical "
        "released titles, preserve every era, genre and exclusion constraint, and do not "
        "repeat any previously attempted song. Prefer songs from different original albums "
        "when several valid alternatives exist. Fill any remaining candidate positions with "
        "other fully compliant artists."
    )


def _reccobeats_replenishment_guidance(
    candidates: list[dict[str, str]],
) -> str:
    """Prefer real ReccoBeats identities without weakening authoritative constraints."""
    lines = [
        f"- {candidate.get('artist', 'Unknown artist')} — "
        f"{candidate.get('title', 'Unknown track')}"
        for candidate in candidates[:24]
        if str(candidate.get("artist", "")).strip()
        and str(candidate.get("title", "")).strip()
    ]
    if not lines:
        return ""
    return (
        "\n\nRECCOBEATS DISCOVERY: the following catalogue-backed recommendations were "
        "derived from tracks already verified in this playlist. Prefer them as a source "
        "of real song identities when they satisfy the original request. They are discovery "
        "candidates, not pre-approved selections: every hard constraint, artist quota, "
        "recording-version rule, creative requirement and forbidden/already-attempted list "
        "remains authoritative. Never include a song only because it appears in this pool. "
        "If the pool is insufficient, propose other canonical released tracks rather than "
        "relaxing a requirement.\n"
        + "\n".join(lines)
    )


def _hard_constraint_guidance(constraints: Any) -> str:
    """Describe only constraints that the downstream validator will actually enforce."""
    if constraints is None or not getattr(constraints, "active", False):
        return ""

    rules: list[str] = []
    release_year = getattr(constraints, "release_year", None)
    release_from = getattr(constraints, "release_year_from", None)
    release_to = getattr(constraints, "release_year_to", None)
    if release_year is not None:
        rules.append(f"original release year must be exactly {release_year}")
    elif release_from is not None and release_to is not None:
        rules.append(
            f"original release year must be between {release_from} and {release_to}, inclusive"
        )
    elif release_from is not None:
        rules.append(f"original release year must be {release_from} or later")
    elif release_to is not None:
        rules.append(f"original release year must be {release_to} or earlier")

    allowed_artists = list(getattr(constraints, "allowed_artists", []) or [])
    excluded_artists = list(getattr(constraints, "excluded_artists", []) or [])
    allowed_albums = list(getattr(constraints, "allowed_albums", []) or [])
    excluded_albums = list(getattr(constraints, "excluded_albums", []) or [])
    artist_country = getattr(constraints, "artist_country", None)
    if allowed_artists:
        rules.append("allowed artists: " + ", ".join(allowed_artists))
    if excluded_artists:
        rules.append("excluded artists: " + ", ".join(excluded_artists))
    if allowed_albums:
        rules.append("allowed albums: " + ", ".join(allowed_albums))
    if excluded_albums:
        rules.append("excluded albums: " + ", ".join(excluded_albums))
    if artist_country:
        rules.append(f"artist country must be {artist_country}")
    if not rules:
        return ""

    return (
        "\n\nENFORCED HARD CONSTRAINTS: the catalogue validator will reject candidates "
        "that do not satisfy these rules. Do not spend candidate slots on known violations. "
        "Use canonical released song titles and original-release chronology, not reissue or "
        "remaster dates.\n- "
        + "\n- ".join(rules)
    )


def _optimized_replenishment_request(prompt: str, count: int) -> tuple[str, int]:
    if not prompt.lstrip().startswith("The original playlist request is:"):
        return prompt, count
    match = _REPLENISHMENT_MISSING_RE.search(prompt)
    if not match:
        return prompt, count
    missing = max(1, int(match.group(1)))
    optimized_count = min(30, max(12, missing * 4, count))
    optimized_prompt = _REPLENISHMENT_COUNT_RE.sub(
        f"Suggest exactly {optimized_count} NEW", prompt, count=1
    )
    optimized_prompt += _quota_replenishment_guidance(optimized_prompt)
    optimized_prompt += _numeric_quota_replenishment_guidance(
        optimized_prompt, optimized_count
    )
    return optimized_prompt, optimized_count


def _repair_quota_prompt(
    request: str,
    count: int,
    quotas: list[Any],
    draft: dict[str, Any],
) -> str:
    requirements = "; ".join(
        f"at least {quota.minimum} tracks by {quota.artist}" for quota in quotas
    )
    current = "\n".join(
        f"- {track.get('artist', 'Unknown artist')} — {track.get('title', 'Unknown track')}"
        for track in draft.get("tracks", [])
        if isinstance(track, dict)
    )
    return (
        f"Repair this playlist for the original request:\n{request}\n\n"
        f"Return exactly {count} distinct tracks. These are independent mandatory artist "
        f"targets with a catalogue-resolution safety margin: {requirements}. Each target "
        "must be satisfied separately; do not combine the artists into one shared quota. "
        "Preserve every other original constraint, including era, genre, exclusions, live, "
        "cover and remix restrictions. Replace unsuitable tracks rather than relaxing a "
        "requirement. Prefer tracks from different original albums whenever possible and "
        "avoid concentrating an artist's selections on one album. Use canonical released "
        f"song titles likely to be found on YouTube Music.\n\nCurrent draft:\n{current or '- None'}"
    )


def _reset_resolution_session(
    quotas: list[Any],
    count: int,
    exact_quotas: list[Any] | None = None,
) -> None:
    """Start a clean catalogue-selection session for one generation request."""
    _ACTIVE_RESOLUTION_QUOTAS.set(tuple(quotas))
    _ACTIVE_EXACT_ARTIST_QUOTAS.set(tuple(exact_quotas or ()))
    _RESOLVED_SESSION_TRACKS.set(())
    _REQUESTED_SESSION_COUNT.set(max(0, int(count)))
    _LAST_INTERPRETED_CONSTRAINTS.set(None)


def _cap_buffered_quotas_at_exact_counts(
    quotas: list[Any],
    exact_quotas: list[Any],
) -> list[Any]:
    if not exact_quotas:
        return quotas

    from backend.artist_quota_detection import ArtistMinimumQuota, artist_matches

    capped: list[Any] = []
    for quota in quotas:
        exact = next(
            (
                item
                for item in exact_quotas
                if artist_matches(quota.artist, item.artist)
                or artist_matches(item.artist, quota.artist)
            ),
            None,
        )
        capped.append(
            ArtistMinimumQuota(quota.artist, exact.count) if exact is not None else quota
        )
    return capped


def _album_key(track: dict[str, Any]) -> str:
    from backend.text_normalization import normalize_identity

    album = str(track.get("album") or "").strip()
    return normalize_identity(album) if album else ""


def _diversity_rank(
    track: dict[str, Any], existing: list[dict[str, Any]]
) -> tuple[int, int, str]:
    """Prefer less represented albums, then less represented artists."""
    from backend.text_normalization import normalize_identity

    album = _album_key(track)
    artist = normalize_identity(
        str(track.get("artists", track.get("artist", "")))
    )
    album_count = sum(1 for item in existing if album and _album_key(item) == album)
    artist_count = sum(
        1
        for item in existing
        if normalize_identity(
            str(item.get("artists", item.get("artist", "")))
        )
        == artist
    )
    return album_count, artist_count, album


def _log_stage(stage: str, started_at: float, **details: Any) -> None:
    elapsed_ms = round((time.perf_counter() - started_at) * 1000)
    record_stage_ms(stage, elapsed_ms)
    suffix = " ".join(f"{key}={value}" for key, value in details.items())
    logger.info(
        "playlist_stage stage=%s elapsed_ms=%s %s", stage, elapsed_ms, suffix
    )


def _select_resolved_tracks(
    resolved: list[dict[str, Any]],
    *,
    youtube: Any,
    artist_matches: Any,
    quota_deficits: Any,
) -> list[dict[str, Any]]:
    """Apply the integrated policy-aware catalogue selection guard."""
    from backend.selection_guard import guarded_select_resolved_tracks

    return guarded_select_resolved_tracks(
        resolved,
        youtube=youtube,
        artist_matches=artist_matches,
        quota_deficits=quota_deficits,
    )


def _dict_tracks(draft: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only the dict-shaped entries of a draft's track list."""
    return [track for track in draft.get("tracks", []) if isinstance(track, dict)]


def _activate_stage_session(stage: str, optimized_prompt: str) -> None:
    """Reset the per-stage replacement/recording/creative context for a fresh draft."""
    from backend.creative_intent import CreativeIntent, activate_creative_intent
    from backend.policy_enforcement import (
        _ACTIVE_POLICY,
        _POLICY_BASE_TRACKS,
        _REPLACEMENT_FINAL_COUNT,
        _REPLACEMENT_MODE,
        parse_replacement_tracks,
    )
    from backend.recording_variants import RecordingVariantPolicy, activate_recording_policy

    if stage == "llm_initial":
        _ACTIVE_POLICY.set(None)
        _POLICY_BASE_TRACKS.set(())
        _REPLACEMENT_MODE.set(False)
        _REPLACEMENT_FINAL_COUNT.set(0)
        activate_recording_policy(RecordingVariantPolicy())
        activate_creative_intent(CreativeIntent())
    elif stage == "llm_replacement":
        base_tracks, final_count = parse_replacement_tracks(optimized_prompt)
        _ACTIVE_POLICY.set(None)
        _POLICY_BASE_TRACKS.set(tuple(base_tracks))
        _REPLACEMENT_MODE.set(True)
        _REPLACEMENT_FINAL_COUNT.set(final_count)
        activate_recording_policy(RecordingVariantPolicy())
        activate_creative_intent(CreativeIntent())


async def _interpret_request(
    config: Any,
    source_prompt: str,
    fallback: Any,
    stage: str,
    is_seed_generation: bool = False,
) -> tuple[dict[str, Any] | None, Any, Any, dict[str, list[str]] | None]:
    """Interpret one request's constraints and recording/creative policy in parallel.

    stage and is_seed_generation are forwarded to _resolve_taste_memory_signal only, to
    scope taste-memory influence to initial text-prompt generation (see that function's
    docstring) -- they play no role in the rest of this function's interpretation.

    Returns (interpreted_payload, assessment, enforced_constraints, taste_signal) and
    raises ValueError when the interpreted request is impossible to satisfy.
    """
    from backend.creative_intent import (
        activate_creative_intent,
        interpret_creative_intent,
        interpret_style_request,
        merge_creative_intents,
    )
    from backend.entity_resolution import canonicalize_interpretation
    from backend.favorites import active_favorite_artist_allowlist
    from backend.metadata_validation import constraints_from_payload
    from backend.prompt_validation import assess_interpretation, assess_prompt
    from backend.recording_variants import activate_recording_policy, interpret_recording_policy
    from backend.request_constraints import open_ended_year_range

    assessment, recording_policy, creative_intent, taste_signal = await asyncio.gather(
        assess_prompt(config, source_prompt),
        interpret_recording_policy(config, source_prompt),
        interpret_creative_intent(config, source_prompt),
        _resolve_taste_memory_signal(config, source_prompt, stage, is_seed_generation),
    )
    if active_favorite_artist_allowlist():
        # The artist pool is hard-restricted to bookmarked favorites below; if the
        # prompt also names a genre/style, that pool may not actually contain any
        # matching tracks, so it needs its own explicit check (see
        # interpret_style_request's docstring).
        style_intent = await interpret_style_request(config, source_prompt)
        creative_intent = merge_creative_intents(creative_intent, style_intent)
    activate_recording_policy(recording_policy)
    activate_creative_intent(creative_intent)
    if assessment.status == "impossible":
        reason = " ".join(assessment.reasons)
        raise ValueError(reason or "The request contains incompatible constraints.")

    interpreted = await canonicalize_interpretation(assessment.interpretation)
    assessment = assess_interpretation(interpreted)
    enforced_constraints = constraints_from_payload(interpreted, fallback=fallback)

    explicit_open_range = open_ended_year_range(source_prompt)
    if explicit_open_range is not None and enforced_constraints.release_year is None:
        lower, upper = explicit_open_range
        enforced_constraints.release_year_from = max(
            lower,
            enforced_constraints.release_year_from
            if enforced_constraints.release_year_from is not None
            else lower,
        )
        enforced_constraints.release_year_to = min(
            upper,
            enforced_constraints.release_year_to
            if enforced_constraints.release_year_to is not None
            else upper,
        )
    return interpreted, assessment, enforced_constraints, taste_signal


async def _replenishment_reccobeats_guidance(stage: str, optimized_count: int) -> str:
    """Return optional ReccoBeats-derived guidance text for a replenishment round."""
    if stage != "llm_replenishment":
        return ""

    verified_anchors = [
        dict(track)
        for track in _RESOLVED_SESSION_TRACKS.get()
        if isinstance(track, dict)
    ]
    reccobeats_candidates: list[dict[str, str]] = []
    if verified_anchors:
        try:
            from backend.reccobeats_features import (
                recommendation_candidates_from_tracks,
            )

            reccobeats_candidates = await recommendation_candidates_from_tracks(
                verified_anchors,
                limit=min(24, max(12, optimized_count)),
                max_anchors=3,
            )
        except Exception as error:  # noqa: BLE001 - optional discovery is fail-open.
            logger.info(
                "reccobeats_replenishment unavailable error=%s",
                type(error).__name__,
            )
    guidance = _reccobeats_replenishment_guidance(reccobeats_candidates)
    logger.info(
        "reccobeats_replenishment anchors=%s candidates=%s applied=%s",
        len(verified_anchors),
        len(reccobeats_candidates),
        bool(guidance),
    )
    return guidance


async def _resolve_taste_memory_signal(
    config: Any, source_prompt: str, stage: str, is_seed_generation: bool = False
) -> dict[str, list[str]] | None:
    """Extract a taste-memory matching signal for this request, or None if the feature is
    off, out of scope for this stage, has no convergent data yet, times out, or anything
    else goes wrong. Never raises: this must never be able to break generation.
    Kept as its own top-level function (not an inline closure) so it can be tested in
    isolation, the same way _initial_reccobeats_guidance is.

    Scoped to the initial text-prompt generation only (not seed mode, not a replacement
    round) -- mirrors _initial_reccobeats_guidance's exact stage/seed gate.
    """
    if stage != "llm_initial" or is_seed_generation:
        return None
    try:
        from backend.local_taste_memory import (
            generation_influence_enabled,
            has_convergent_taste_memory,
            interpret_taste_signal,
        )

        if not generation_influence_enabled() or not has_convergent_taste_memory():
            return None
        return await asyncio.wait_for(
            interpret_taste_signal(config, source_prompt), timeout=3.0
        )
    except Exception:
        return None


async def _initial_reccobeats_guidance(
    config: Any,
    stage: str,
    prompt: str,
    is_seed_generation: bool = False,
) -> str:
    """Ground the very first draft in real ReccoBeats catalogue songs before any tracks exist.

    Unlike the replenishment round (which reuses tracks the LLM already picked), this
    interprets the raw request into a handful of real anchor songs first, so even the
    initial draft has some catalogue grounding. This is intentionally a single anchor
    interpretation call plus a single recommendation discovery call — not the full
    multi-stage, multi-batch orchestration that was reverted for being too slow (see
    the "restore fast generation runtime baseline" history for `reccobeats_runtime.py`).

    The anchor interpretation call has no built-in timeout of its own — it can try every
    model in `config.model_chain` (primary plus up to 8 fallbacks) at up to 45s each, so
    it is wrapped here in a short hard deadline. This is an optional grounding step, not
    a hard requirement, and must not be allowed to multiply the worst-case latency of the
    already-unbounded constraint-interpretation call that runs alongside it.

    For seed-based generation (`is_seed_generation=True`) this step is skipped entirely:
    seed requests already get real, evidence-backed grounding from Last.fm (see
    `_seed_evidence_guidance` in main.py), and a live comparative check (2026-08-15, two
    unrelated seeds -- a niche French-house track and a mainstream global pop hit) found
    ReccoBeats' single-seed `/track/recommendation` output to be genre-incoherent noise in
    both cases, contributing effectively zero usable tracks to the final playlist while
    costing a real ~7s of latency. Given generation speed is a standing priority, that
    latency isn't worth spending on a step with no observed benefit for seed mode.
    """
    if stage != "llm_initial" or is_seed_generation:
        return ""

    reccobeats_candidates: list[dict[str, str]] = []
    try:
        from backend.reccobeats_anchors import interpret_reccobeats_anchors
        from backend.reccobeats_features import (
            recommendation_candidates_from_tracks,
        )

        anchors = await asyncio.wait_for(
            interpret_reccobeats_anchors(config, prompt),
            timeout=INITIAL_ANCHOR_TIMEOUT_SECONDS,
        )
        if anchors:
            reccobeats_candidates = await recommendation_candidates_from_tracks(
                anchors,
                limit=24,
                max_anchors=3,
            )
    except Exception as error:  # noqa: BLE001 - optional discovery is fail-open.
        logger.info(
            "reccobeats_initial_anchors unavailable error=%s",
            type(error).__name__,
        )

    from backend.reccobeats_guidance import reccobeats_guidance as build_guidance_text

    guidance = build_guidance_text(reccobeats_candidates)
    logger.info(
        "reccobeats_initial candidates=%s applied=%s",
        len(reccobeats_candidates),
        bool(guidance),
    )
    return guidance


async def generate_playlist_draft(
    config: Any,
    prompt: str,
    count: int,
    is_seed_generation: bool = False,
) -> dict[str, Any]:
    """Generate and validate one draft without mutating imported modules."""
    from backend.artist_quota_detection import (
        exact_quota_guidance,
        extract_artist_exact_quotas,
        extract_artist_minimum_quotas,
        quota_deficits,
        quota_guidance,
        user_request_text,
    )
    from backend.creative_intent import assess_creative_fit, creative_repair_prompt
    from backend.llm import generate_playlist_draft as raw_generate_playlist_draft
    from backend.metadata_validation import (
        activate_constraints,
        active_constraints,
        extract_metadata_constraints,
    )
    from backend.favorites import active_favorite_artist_allowlist
    from backend.playlist_policy import hard_allowed_artists, policy_from_payload
    from backend.policy_consistency import apply_playlist_policy
    from backend.policy_enforcement import _ACTIVE_POLICY
    from backend.request_constraints import buffered_artist_quotas

    optimized_prompt, optimized_count = _optimized_replenishment_request(
        prompt, count
    )
    stage = _stage_name(optimized_prompt)
    _activate_stage_session(stage, optimized_prompt)

    started_at = time.perf_counter()
    should_interpret = stage in {"llm_initial", "llm_replacement"}
    source_prompt = _constraint_source(optimized_prompt, stage)
    user_request = user_request_text(optimized_prompt)
    artist_quotas = extract_artist_minimum_quotas(user_request)
    exact_artist_quotas = extract_artist_exact_quotas(user_request)
    if should_interpret:
        _reset_resolution_session(artist_quotas, count, exact_artist_quotas)
    generation_quotas = buffered_artist_quotas(
        artist_quotas, optimized_count
    )
    generation_quotas = _cap_buffered_quotas_at_exact_counts(
        generation_quotas,
        exact_artist_quotas,
    )
    submitted_prompt = optimized_prompt + quota_guidance(generation_quotas)
    submitted_prompt += exact_quota_guidance(exact_artist_quotas)
    submitted_prompt += (
        "\n\nALBUM DIVERSITY: when several compliant tracks are available, prefer "
        "different original albums. Avoid selecting many tracks from the same "
        "album unless the user explicitly asks for that album."
    )
    fallback = (
        extract_metadata_constraints(source_prompt)
        if should_interpret
        else None
    )
    interpreted: dict[str, Any] | None = None
    assessment = None
    enforced_constraints = None
    try:
        if should_interpret:
            interpreted, assessment, enforced_constraints, taste_signal = (
                await _interpret_request(
                    config, source_prompt, fallback, stage, is_seed_generation
                )
            )
            _LAST_INTERPRETED_CONSTRAINTS.set(interpreted)
            activate_taste_memory_signal(taste_signal)
        else:
            enforced_constraints = active_constraints()

        hard_guidance = _hard_constraint_guidance(enforced_constraints)
        submitted_prompt += hard_guidance

        from backend.local_taste_memory import taste_memory_guidance

        submitted_prompt += taste_memory_guidance(active_taste_memory_signal())

        reccobeats_guidance = await _replenishment_reccobeats_guidance(
            stage, optimized_count
        ) or await _initial_reccobeats_guidance(
            config, stage, source_prompt, is_seed_generation
        )
        submitted_prompt += reccobeats_guidance

        async def repair_quota_deficits(
            current: dict[str, Any],
        ) -> tuple[dict[str, Any], list[Any]]:
            deficits = quota_deficits(_dict_tracks(current), generation_quotas)
            for _ in range(2):
                if not deficits:
                    break
                repair_prompt = _repair_quota_prompt(
                    user_request,
                    optimized_count,
                    generation_quotas,
                    current,
                )
                repaired = await raw_generate_playlist_draft(
                    config,
                    repair_prompt + hard_guidance + reccobeats_guidance,
                    optimized_count,
                )
                repaired_deficits = quota_deficits(
                    _dict_tracks(repaired),
                    generation_quotas,
                )
                if sum(item.minimum for item in repaired_deficits) >= sum(
                    item.minimum for item in deficits
                ):
                    break
                current = repaired
                deficits = repaired_deficits
            return current, deficits

        draft = await raw_generate_playlist_draft(
            config, submitted_prompt, optimized_count
        )
        draft, generation_deficits = await repair_quota_deficits(draft)

        creative_conflicts = await assess_creative_fit(config, _dict_tracks(draft))
        for _ in range(_creative_repair_rounds(stage)):
            if not creative_conflicts:
                break
            repaired = await raw_generate_playlist_draft(
                config,
                creative_repair_prompt(
                    user_request,
                    optimized_count,
                    draft,
                    creative_conflicts,
                )
                + hard_guidance
                + quota_guidance(generation_quotas)
                + exact_quota_guidance(exact_artist_quotas),
                optimized_count,
            )
            repaired, repaired_deficits = await repair_quota_deficits(repaired)
            repaired_conflicts = await assess_creative_fit(
                config, _dict_tracks(repaired)
            )
            if len(repaired_conflicts) >= len(creative_conflicts):
                break
            draft = repaired
            generation_deficits = repaired_deficits
            creative_conflicts = repaired_conflicts

        if creative_conflicts:
            conflict_by_index = {
                conflict.index: conflict for conflict in creative_conflicts
            }
            accepted_tracks: list[dict[str, Any]] = []
            rejected_tracks: list[dict[str, Any]] = []
            for index, track in enumerate(_dict_tracks(draft), start=1):
                conflict = conflict_by_index.get(index)
                if conflict is None:
                    accepted_tracks.append(track)
                    continue
                rejected_tracks.append(
                    {
                        **track,
                        "unresolved_reason": "creative_intent_validation",
                        "creative_intent_reason": conflict.reason,
                        "creative_intent_confidence": conflict.confidence,
                    }
                )
            draft["tracks"] = accepted_tracks
            draft["creative_intent_rejected"] = rejected_tracks
            generation_deficits = quota_deficits(
                accepted_tracks,
                generation_quotas,
            )

        effective_deficits = quota_deficits(_dict_tracks(draft), artist_quotas)
        if should_interpret:
            constraints = enforced_constraints
            policy = policy_from_payload(interpreted, prompt=source_prompt)
            _ACTIVE_POLICY.set(policy)
            constraints.allowed_artists = hard_allowed_artists(
                constraints.allowed_artists,
                policy,
                prompt=source_prompt,
            )
            favorite_allowlist = active_favorite_artist_allowlist()
            if favorite_allowlist:
                constraints.allowed_artists = list(
                    dict.fromkeys([*constraints.allowed_artists, *favorite_allowlist])
                )
            constraints.artist_name = (
                constraints.allowed_artists[0]
                if len(constraints.allowed_artists) == 1
                else None
            )
            activate_constraints(constraints)
            draft, policy_issues = apply_playlist_policy(
                draft, policy, requested_count=optimized_count
            )
            draft["prompt_assessment"] = (
                assessment.as_dict()
                if assessment
                else {"status": "valid", "reasons": []}
            )
            logger.info(
                "playlist_constraints stage=%s constraints=%s policy=%s "
                "issues=%s artist_quota_deficits=%s "
                "buffered_quota_deficits=%s exact_artist_quotas=%s assessment=%s",
                stage,
                asdict(constraints),
                asdict(policy),
                policy_issues,
                [asdict(item) for item in effective_deficits],
                [asdict(item) for item in generation_deficits],
                [asdict(item) for item in exact_artist_quotas],
                draft["prompt_assessment"],
            )
        else:
            active_policy = _ACTIVE_POLICY.get()
            if active_policy is not None:
                draft, _ = apply_playlist_policy(
                    draft,
                    active_policy,
                    requested_count=max(
                        optimized_count,
                        len(draft.get("tracks", [])),
                    ),
                )
        return draft
    finally:
        _log_stage(
            stage,
            started_at,
            requested=count,
            submitted=optimized_count,
            creative_repair_limit=_creative_repair_rounds(stage),
        )


async def discover_from_anchors(
    anchors: list[dict[str, str]],
    *,
    limit: int = 40,
    max_anchors: int = 3,
) -> list[dict[str, str]]:
    """Run prompt-anchor discovery with explicit timing instrumentation."""
    from backend.lastfm_discovery import (
        discover_from_anchors as raw_discover_from_anchors,
    )

    started_at = time.perf_counter()
    try:
        return await raw_discover_from_anchors(
            anchors,
            limit=limit,
            max_anchors=max_anchors,
        )
    finally:
        _log_stage("lastfm_prompt_discovery", started_at)


async def discover_for_seed(
    artist: str,
    title: str,
    *,
    limit: int = 40,
    broaden: bool = False,
    api_key: str | None = None,
    client: Any | None = None,
) -> list[dict[str, str]]:
    """Run seed discovery with explicit timing instrumentation."""
    from backend.lastfm_discovery import (
        discover_for_seed as raw_discover_for_seed,
    )

    started_at = time.perf_counter()
    try:
        return await raw_discover_for_seed(
            artist,
            title,
            limit=limit,
            broaden=broaden,
            api_key=api_key,
            client=client,
        )
    finally:
        _log_stage("lastfm_seed_discovery", started_at)


async def resolve_candidates(
    candidates: list[dict[str, str]],
    exclusions: dict[str, bool],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve catalogue candidates and enforce recording-version policy before selection."""
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
        effective_exclusions = effective_resolver_options(
            exclusions,
            recording_policy,
        )
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
        return selected, unresolved
    finally:
        _log_stage(
            "catalogue_resolution",
            started_at,
            candidates=len(candidates),
        )