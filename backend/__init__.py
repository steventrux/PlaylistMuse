"""PlaylistMuse backend package bootstrap."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import asdict
from functools import wraps
from typing import Any

logger = logging.getLogger("playlistmuse.performance")
_REPLENISHMENT_MISSING_RE = re.compile(r"still needs\s+(\d+)\s+resolvable songs", re.I)
_REPLENISHMENT_COUNT_RE = re.compile(r"Suggest exactly\s+\d+\s+NEW", re.I)
_STRICT_MAJORITY_ARTIST_RE = re.compile(
    r"\bpi[uù]\s+della\s+met[aà].{0,80}?"
    r"(?:di|dei|degli|delle)\s+([^,;.!\n]{1,120})",
    re.IGNORECASE,
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
    """Extract only the user's request from internal generation instructions."""
    if "User request:\n" in prompt:
        return prompt.split("User request:\n", 1)[1].strip()
    if stage == "llm_replacement" and "Original playlist request:" in prompt:
        tail = prompt.split("Original playlist request:", 1)[1]
        return tail.split("\n", 1)[0].strip()
    return prompt.strip()


def _quota_replenishment_guidance(prompt: str) -> str:
    if not prompt.lstrip().startswith("The original playlist request is:"):
        return ""
    request = prompt.split("The original playlist request is:\n", 1)[1].split("\n", 1)[0]
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


def _optimized_replenishment_request(prompt: str, count: int) -> tuple[str, int]:
    if not prompt.lstrip().startswith("The original playlist request is:"):
        return prompt, count
    match = _REPLENISHMENT_MISSING_RE.search(prompt)
    if not match:
        return prompt, count
    missing = max(1, int(match.group(1)))
    optimized_count = min(20, max(4, missing * 2))
    optimized_prompt = _REPLENISHMENT_COUNT_RE.sub(
        f"Suggest exactly {optimized_count} NEW",
        prompt,
        count=1,
    )
    optimized_prompt += _quota_replenishment_guidance(optimized_prompt)
    return optimized_prompt, min(count, optimized_count)


def _log_stage(stage: str, started_at: float, **details: Any) -> None:
    elapsed_ms = round((time.perf_counter() - started_at) * 1000)
    suffix = " ".join(f"{key}={value}" for key, value in details.items())
    logger.info("playlist_stage stage=%s elapsed_ms=%s %s", stage, elapsed_ms, suffix)


def _install_generation_wrappers() -> None:
    from backend import lastfm_discovery, llm, youtube
    from backend.entity_resolution import canonicalize_interpretation
    from backend.metadata_validation import (
        activate_constraints,
        constraints_from_payload,
        extract_metadata_constraints,
    )
    from backend.playlist_policy import (
        apply_playlist_policy,
        hard_allowed_artists,
        policy_from_payload,
    )
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
                        reason = " ".join(assessment.reasons)
                        raise ValueError(
                            reason or "The request contains incompatible constraints."
                        )
                    interpreted = await canonicalize_interpretation(
                        assessment.interpretation
                    )
                    assessment = assess_interpretation(interpreted)

                draft = await original_generate(config, optimized_prompt, optimized_count)
                if should_interpret:
                    constraints = constraints_from_payload(interpreted, fallback=fallback)
                    policy = policy_from_payload(interpreted, prompt=source_prompt)
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
                        draft,
                        policy,
                        requested_count=optimized_count,
                    )
                    draft["prompt_assessment"] = (
                        assessment.as_dict()
                        if assessment
                        else {"status": "valid", "reasons": []}
                    )
                    logger.info(
                        "playlist_constraints stage=%s constraints=%s policy=%s "
                        "issues=%s assessment=%s",
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


_install_generation_wrappers()
