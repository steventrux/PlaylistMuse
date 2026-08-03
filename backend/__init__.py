"""PlaylistMuse backend package bootstrap."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import asdict
from functools import wraps
from typing import Any

logger = logging.getLogger("playlistmuse.performance")
_REPLENISHMENT_MISSING_RE = re.compile(r"still needs\s+(\d+)\s+resolvable songs", re.I)
_REPLENISHMENT_COUNT_RE = re.compile(r"Suggest exactly\s+\d+\s+NEW", re.I)


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


def _install_generation_wrappers() -> None:
    from backend import lastfm_discovery, llm, youtube
    from backend.constraint_interpreter import interpret_constraints
    from backend.metadata_validation import (
        activate_constraints,
        constraints_from_payload,
        extract_metadata_constraints,
    )

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
            interpretation_task = (
                asyncio.create_task(interpret_constraints(config, source_prompt))
                if should_interpret
                else None
            )
            try:
                draft = await original_generate(config, optimized_prompt, optimized_count)
                if interpretation_task is not None:
                    interpreted = await interpretation_task
                    constraints = constraints_from_payload(interpreted, fallback=fallback)
                    activate_constraints(constraints)
                    logger.info(
                        "playlist_constraints stage=%s constraints=%s",
                        stage,
                        asdict(constraints),
                    )
                return draft
            finally:
                if interpretation_task is not None and not interpretation_task.done():
                    interpretation_task.cancel()
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
