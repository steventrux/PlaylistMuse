"""PlaylistMuse backend package bootstrap."""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from dataclasses import asdict
from functools import wraps
from typing import Any

logger = logging.getLogger("playlistmuse.performance")
_REPLENISHMENT_MISSING_RE = re.compile(r"still needs\s+(\d+)\s+resolvable songs", re.I)
_REPLENISHMENT_COUNT_RE = re.compile(r"Suggest exactly\s+\d+\s+NEW", re.I)
_POLICY_PROMPT_EXTENSION = """

Also extract playlist-level policy fields. Add these keys to the returned JSON object:
- required_tracks: exact named songs that must be included, each as {artist, title}
- excluded_tracks: exact named songs that must not be included
- minimum_allowed_artist_ratio and maximum_allowed_artist_ratio: 0.0 to 1.0
- minimum_allowed_artist_count and maximum_allowed_artist_count: integer or null
- max_tracks_per_artist: integer or null
- lyrics_language: requested sung language or null
- release_country: requested release country or null
- target_market: market where songs must be popular or null
- soundtrack_title: named film, series, game or other work soundtrack or null
- soundtrack_type: film, series, game, musical, other or null
- constraint_status: valid, ambiguous or impossible
- status_reasons: concise user-facing reasons written in the same language as the request

Add a 0.0 to 1.0 confidence entry for every new field in field_confidence.
Interpret proportional wording in any language: mostly, at least half, a few, no more than,
maximum, minimum, one or two, and equivalent expressions. A named required track is not a
style reference. Do not claim that lyrics language, market popularity or soundtrack membership
has been externally verified; only extract the user's intent.

Use constraint_status="impossible" only when no track or playlist can satisfy all explicit
requirements simultaneously, for example music from the 1990s that must also be published
after 2000. Use constraint_status="ambiguous" when two or more reasonable interpretations
remain possible and selecting one would require guessing. Use "valid" otherwise. Never solve a
contradiction by silently discarding one constraint. Explain every ambiguous or impossible
classification in status_reasons, in the user's language.
"""


def _unicode_normalize(value: str) -> str:
    """Normalize identity text while preserving letters and numbers from every script."""
    decomposed = unicodedata.normalize("NFKD", str(value).casefold())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    separated = "".join(char if char.isalnum() else " " for char in plain)
    return " ".join(separated.split())


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
    """Extract only the user's request from internal generation instructions."""
    if "User request:\n" in prompt:
        return prompt.split("User request:\n", 1)[1].strip()
    if stage == "llm_replacement" and "Original playlist request:" in prompt:
        tail = prompt.split("Original playlist request:", 1)[1]
        return tail.split("\n", 1)[0].strip()
    return prompt.strip()


def _optimized_replenishment_request(prompt: str, count: int) -> tuple[str, int]:
    if not prompt.lstrip().startswith("The original playlist request is:"):
        return prompt, count
    match = _REPLENISHMENT_MISSING_RE.search(prompt)
    if not match:
        return prompt, count
    missing = max(1, int(match.group(1)))
    optimized_count = min(20, max(4, missing * 2))
    if optimized_count >= count:
        return prompt, count
    return (
        _REPLENISHMENT_COUNT_RE.sub(
            f"Suggest exactly {optimized_count} NEW",
            prompt,
            count=1,
        ),
        optimized_count,
    )


def _log_stage(stage: str, started_at: float, **details: Any) -> None:
    elapsed_ms = round((time.perf_counter() - started_at) * 1000)
    suffix = " ".join(f"{key}={value}" for key, value in details.items())
    logger.info("playlist_stage stage=%s elapsed_ms=%s %s", stage, elapsed_ms, suffix)


def _install_unicode_normalization() -> None:
    """Use one Unicode-safe identity function across catalogue and constraint modules."""
    from backend import entity_resolution, metadata_validation, playlist_policy, youtube

    metadata_validation._normalize = _unicode_normalize
    playlist_policy._normalize = _unicode_normalize
    entity_resolution._normalize = _unicode_normalize
    youtube._normalize_identity = _unicode_normalize


def _install_interpreter_policy_schema() -> None:
    """Extend the multilingual interpreter without adding another model request."""
    from backend import constraint_interpreter

    if getattr(constraint_interpreter, "_playlistmuse_policy_schema", False):
        return
    constraint_interpreter.SYSTEM_PROMPT += _POLICY_PROMPT_EXTENSION
    constraint_interpreter.INTERPRETER_SCHEMA_VERSION = 4
    constraint_interpreter.INTERPRETER_PROMPT_VERSION = "2026-08-03.4"
    constraint_interpreter._playlistmuse_policy_schema = True


def _install_prompt_validation_route() -> None:
    """Expose prompt assessment through the router already mounted by the application."""
    from fastapi import HTTPException

    from backend.config import load_config
    from backend.prompt_validation import assess_prompt
    from backend.youtube_routes import router

    if getattr(router, "_playlistmuse_prompt_validation", False):
        return

    async def validate_playlist_prompt(payload: dict[str, Any]) -> dict[str, Any]:
        prompt = " ".join(str(payload.get("prompt", "")).split())
        if len(prompt) < 3:
            raise HTTPException(status_code=422, detail="Describe the playlist you want.")
        if len(prompt) > 1950:
            raise HTTPException(status_code=422, detail="The playlist request is too long.")
        assessment = await assess_prompt(load_config(), prompt)
        return assessment.as_dict()

    router.add_api_route(
        "/playlists/validate-prompt",
        validate_playlist_prompt,
        methods=["POST"],
        tags=["playlists"],
    )
    router._playlistmuse_prompt_validation = True  # type: ignore[attr-defined]


def _install_generation_wrappers() -> None:
    from backend import lastfm_discovery, llm, youtube
    from backend.entity_resolution import canonicalize_interpretation
    from backend.metadata_validation import (
        activate_constraints,
        constraints_from_payload,
        extract_metadata_constraints,
    )
    from backend.playlist_policy import apply_playlist_policy, policy_from_payload
    from backend.prompt_validation import assess_interpretation, assess_prompt

    original_generate = llm.generate_playlist_draft
    if not getattr(original_generate, "_playlistmuse_generation_wrapper", False):

        @wraps(original_generate)
        async def wrapped_generate_playlist_draft(
            config: Any,
            prompt: str,
            count: int,
        ) -> dict[str, Any]:
            optimized_prompt, optimized_count = _optimized_replenishment_request(prompt, count)
            stage = _stage_name(optimized_prompt)
            started_at = time.perf_counter()
            should_interpret = stage in {"llm_initial", "llm_replacement"}
            source_prompt = _constraint_source(optimized_prompt, stage)
            fallback = extract_metadata_constraints(source_prompt) if should_interpret else None
            interpreted: dict[str, Any] | None = None
            assessment = None
            try:
                if should_interpret:
                    assessment = await assess_prompt(config, source_prompt)
                    if assessment.status == "impossible":
                        reason = " ".join(assessment.reasons) or "The request contains incompatible constraints."
                        raise ValueError(reason)
                    interpreted = await canonicalize_interpretation(assessment.interpretation)
                    assessment = assess_interpretation(interpreted)

                draft = await original_generate(config, optimized_prompt, optimized_count)
                if should_interpret:
                    constraints = constraints_from_payload(interpreted, fallback=fallback)
                    policy = policy_from_payload(interpreted)
                    activate_constraints(constraints)
                    draft, policy_issues = apply_playlist_policy(
                        draft,
                        policy,
                        allowed_artists=constraints.allowed_artists,
                        requested_count=optimized_count,
                    )
                    draft["prompt_assessment"] = assessment.as_dict() if assessment else {"status": "valid", "reasons": []}
                    logger.info(
                        "playlist_constraints stage=%s constraints=%s policy=%s issues=%s assessment=%s",
                        stage,
                        asdict(constraints),
                        asdict(policy),
                        policy_issues,
                        draft["prompt_assessment"],
                    )
                return draft
            finally:
                _log_stage(
                    stage,
                    started_at,
                    requested=count,
                    submitted=optimized_count,
                )

        wrapped_generate_playlist_draft._playlistmuse_generation_wrapper = True  # type: ignore[attr-defined]
        llm.generate_playlist_draft = wrapped_generate_playlist_draft

    original_discover = lastfm_discovery.discover_from_anchors
    if not getattr(original_discover, "_playlistmuse_timing_wrapper", False):

        @wraps(original_discover)
        async def wrapped_discover_from_anchors(*args: Any, **kwargs: Any) -> Any:
            started_at = time.perf_counter()
            try:
                return await original_discover(*args, **kwargs)
            finally:
                _log_stage("lastfm_prompt_discovery", started_at)

        wrapped_discover_from_anchors._playlistmuse_timing_wrapper = True  # type: ignore[attr-defined]
        lastfm_discovery.discover_from_anchors = wrapped_discover_from_anchors

    original_seed_discover = lastfm_discovery.discover_for_seed
    if not getattr(original_seed_discover, "_playlistmuse_timing_wrapper", False):

        @wraps(original_seed_discover)
        async def wrapped_discover_for_seed(*args: Any, **kwargs: Any) -> Any:
            started_at = time.perf_counter()
            try:
                return await original_seed_discover(*args, **kwargs)
            finally:
                _log_stage("lastfm_seed_discovery", started_at)

        wrapped_discover_for_seed._playlistmuse_timing_wrapper = True  # type: ignore[attr-defined]
        lastfm_discovery.discover_for_seed = wrapped_discover_for_seed

    original_resolve = youtube.resolve_candidates
    if not getattr(original_resolve, "_playlistmuse_timing_wrapper", False):

        @wraps(original_resolve)
        async def wrapped_resolve_candidates(*args: Any, **kwargs: Any) -> Any:
            started_at = time.perf_counter()
            candidates = args[0] if args else kwargs.get("candidates", [])
            try:
                return await original_resolve(*args, **kwargs)
            finally:
                _log_stage("catalogue_resolution", started_at, candidates=len(candidates))

        wrapped_resolve_candidates._playlistmuse_timing_wrapper = True  # type: ignore[attr-defined]
        youtube.resolve_candidates = wrapped_resolve_candidates


_install_unicode_normalization()
_install_interpreter_policy_schema()
_install_prompt_validation_route()
_install_generation_wrappers()
