"""Explicit request-scoped generation orchestration and catalogue selection."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from contextvars import ContextVar
from dataclasses import asdict
from typing import Any

logger = logging.getLogger("playlistmuse.performance")

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


def _stage_name(prompt: str) -> str:
    normalized = prompt.lstrip()
    if normalized.startswith("The original playlist request is:"):
        return "llm_replenishment"
    if normalized.startswith("Create the final playlist for this request:"):
        return "llm_guided"
    if normalized.startswith("Suggest exactly 6 strong replacement candidates"):
        return "llm_replacement"
    return "llm_initial"


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


async def generate_playlist_draft(
    config: Any,
    prompt: str,
    count: int,
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
    from backend.entity_resolution import canonicalize_interpretation
    from backend.llm import generate_playlist_draft as raw_generate_playlist_draft
    from backend.metadata_validation import (
        activate_constraints,
        constraints_from_payload,
        extract_metadata_constraints,
    )
    from backend.playlist_policy import hard_allowed_artists, policy_from_payload
    from backend.policy_consistency import apply_playlist_policy
    from backend.policy_enforcement import (
        _ACTIVE_POLICY,
        _POLICY_BASE_TRACKS,
        _REPLACEMENT_FINAL_COUNT,
        _REPLACEMENT_MODE,
        parse_replacement_tracks,
    )
    from backend.prompt_validation import assess_interpretation, assess_prompt
    from backend.recording_variants import (
        RecordingVariantPolicy,
        activate_recording_policy,
        interpret_recording_policy,
    )
    from backend.request_constraints import (
        buffered_artist_quotas,
        open_ended_year_range,
    )

    optimized_prompt, optimized_count = _optimized_replenishment_request(
        prompt, count
    )
    stage = _stage_name(optimized_prompt)
    if stage == "llm_initial":
        _ACTIVE_POLICY.set(None)
        _POLICY_BASE_TRACKS.set(())
        _REPLACEMENT_MODE.set(False)
        _REPLACEMENT_FINAL_COUNT.set(0)
        activate_recording_policy(RecordingVariantPolicy())
    elif stage == "llm_replacement":
        base_tracks, final_count = parse_replacement_tracks(optimized_prompt)
        _ACTIVE_POLICY.set(None)
        _POLICY_BASE_TRACKS.set(tuple(base_tracks))
        _REPLACEMENT_MODE.set(True)
        _REPLACEMENT_FINAL_COUNT.set(final_count)
        activate_recording_policy(RecordingVariantPolicy())

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
    try:
        if should_interpret:
            assessment, recording_policy = await asyncio.gather(
                assess_prompt(config, source_prompt),
                interpret_recording_policy(config, source_prompt),
            )
            activate_recording_policy(recording_policy)
            if assessment.status == "impossible":
                reason = " ".join(assessment.reasons)
                raise ValueError(
                    reason
                    or "The request contains incompatible constraints."
                )
            interpreted = await canonicalize_interpretation(
                assessment.interpretation
            )
            assessment = assess_interpretation(interpreted)

        draft = await raw_generate_playlist_draft(
            config, submitted_prompt, optimized_count
        )
        generation_deficits = quota_deficits(
            [
                track
                for track in draft.get("tracks", [])
                if isinstance(track, dict)
            ],
            generation_quotas,
        )
        for _ in range(2):
            if not generation_deficits:
                break
            repaired = await raw_generate_playlist_draft(
                config,
                _repair_quota_prompt(
                    user_request,
                    optimized_count,
                    generation_quotas,
                    draft,
                ),
                optimized_count,
            )
            repaired_deficits = quota_deficits(
                [
                    track
                    for track in repaired.get("tracks", [])
                    if isinstance(track, dict)
                ],
                generation_quotas,
            )
            if sum(item.minimum for item in repaired_deficits) >= sum(
                item.minimum for item in generation_deficits
            ):
                break
            draft = repaired
            generation_deficits = repaired_deficits

        effective_deficits = quota_deficits(
            [
                track
                for track in draft.get("tracks", [])
                if isinstance(track, dict)
            ],
            artist_quotas,
        )
        if should_interpret:
            constraints = constraints_from_payload(
                interpreted, fallback=fallback
            )
            explicit_open_range = open_ended_year_range(source_prompt)
            if explicit_open_range is not None:
                constraints.release_year = None
                constraints.release_year_from = explicit_open_range[0]
                constraints.release_year_to = explicit_open_range[1]
            policy = policy_from_payload(interpreted, prompt=source_prompt)
            _ACTIVE_POLICY.set(policy)
            constraints.allowed_artists = hard_allowed_artists(
                constraints.allowed_artists,
                policy,
                prompt=source_prompt,
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
        resolved, variant_rejected = filter_resolved_recording_variants(
            resolved,
            recording_policy,
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
