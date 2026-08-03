"""PlaylistMuse backend package bootstrap."""

from __future__ import annotations

import logging
import re
import time
from functools import wraps
from typing import Any

logger = logging.getLogger("playlistmuse.performance")
_REPLENISHMENT_MISSING_RE = re.compile(r"still needs\s+(\d+)\s+resolvable songs", re.I)
_REPLENISHMENT_COUNT_RE = re.compile(r"Suggest exactly\s+\d+\s+NEW", re.I)
_STYLE_REFERENCE_RE = re.compile(
    r"\b(?:come|simile(?:\s+(?:a|ai|agli|alle))?|ispirat[oaie]\s+(?:a|da)|"
    r"similar(?:\s+to)?|like|inspired\s+by)\b",
    re.I,
)
_DIRECT_ARTIST_RE = re.compile(
    r"\b(?:musica|music|brani|canzoni|songs?|tracks?|playlist)\s+"
    r"(?:di|dei|degli|delle|by|from)\s+"
    r"([\wÀ-ÿ0-9&.' -]{1,100}?)"
    r"(?=\s+(?:per|for|da|to|durante|during)\b|[,.!?]|$)",
    re.I,
)
_DECADE_RE = re.compile(
    r"\b(?:rock|pop|metal|jazz|blues|punk|rap|hip[- ]?hop|musica|music|"
    r"brani|canzoni|songs?|tracks?)\s+(?:degli\s+)?anni\s*['’]?\s*(\d{2})\b",
    re.I,
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


def _optimized_replenishment_request(prompt: str, count: int) -> tuple[str, int]:
    """Reduce oversized refill requests while preserving the requested result count."""
    if not prompt.lstrip().startswith("The original playlist request is:"):
        return prompt, count
    match = _REPLENISHMENT_MISSING_RE.search(prompt)
    if not match:
        return prompt, count
    missing = max(1, int(match.group(1)))
    optimized_count = min(20, max(4, missing * 2))
    if optimized_count >= count:
        return prompt, count
    optimized_prompt = _REPLENISHMENT_COUNT_RE.sub(
        f"Suggest exactly {optimized_count} NEW",
        prompt,
        count=1,
    )
    return optimized_prompt, optimized_count


def _log_stage(stage: str, started_at: float, **details: Any) -> None:
    elapsed_ms = round((time.perf_counter() - started_at) * 1000)
    suffix = " ".join(f"{key}={value}" for key, value in details.items())
    logger.info("playlist_stage stage=%s elapsed_ms=%s %s", stage, elapsed_ms, suffix)


def _decade_bounds(short_year: str) -> tuple[int, int]:
    value = int(short_year)
    start = (2000 if value < 30 else 1900) + value
    return start, start + 9


def _install_natural_constraint_parser() -> None:
    """Add hard constraints for direct artist ownership and named decades.

    Similarity language remains editorial guidance and never activates these inferred
    filters. Explicit constraints already recognised by metadata_validation retain
    priority.
    """
    from backend import metadata_validation

    original_extract = metadata_validation.extract_metadata_constraints
    if getattr(original_extract, "_playlistmuse_natural_constraints", False):
        return

    @wraps(original_extract)
    def wrapped_extract_metadata_constraints(prompt: str) -> Any:
        constraints = original_extract(prompt)
        normalized = " ".join(str(prompt).split())
        if _STYLE_REFERENCE_RE.search(normalized):
            return constraints

        if constraints.artist_name is None:
            artist_match = _DIRECT_ARTIST_RE.search(normalized)
            if artist_match:
                artist = " ".join(artist_match.group(1).split()).strip(" .,-")
                if artist:
                    constraints.artist_name = artist

        if (
            constraints.release_year is None
            and constraints.release_year_from is None
            and constraints.release_year_to is None
        ):
            decade_match = _DECADE_RE.search(normalized)
            if decade_match:
                start, end = _decade_bounds(decade_match.group(1))
                constraints.release_year_from = start
                constraints.release_year_to = end

        return constraints

    wrapped_extract_metadata_constraints._playlistmuse_natural_constraints = True  # type: ignore[attr-defined]
    metadata_validation.extract_metadata_constraints = wrapped_extract_metadata_constraints


def _install_generation_wrappers() -> None:
    """Install request-scoped constraints, timing and bounded refill optimization."""
    from backend import lastfm_discovery, llm, youtube
    from backend.metadata_validation import activate_constraints_from_prompt

    original_generate = llm.generate_playlist_draft
    if not getattr(original_generate, "_playlistmuse_generation_wrapper", False):

        @wraps(original_generate)
        async def wrapped_generate_playlist_draft(
            config: Any,
            prompt: str,
            count: int,
        ) -> dict[str, Any]:
            optimized_prompt, optimized_count = _optimized_replenishment_request(
                prompt,
                count,
            )
            activate_constraints_from_prompt(optimized_prompt)
            stage = _stage_name(optimized_prompt)
            started_at = time.perf_counter()
            try:
                return await original_generate(
                    config,
                    optimized_prompt,
                    optimized_count,
                )
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
                _log_stage(
                    "catalogue_resolution",
                    started_at,
                    candidates=len(candidates),
                )

        wrapped_resolve_candidates._playlistmuse_timing_wrapper = True  # type: ignore[attr-defined]
        youtube.resolve_candidates = wrapped_resolve_candidates


_install_natural_constraint_parser()
_install_generation_wrappers()
