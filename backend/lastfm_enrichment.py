"""AI-written editorial explanations for Last.fm-sourced track candidates."""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Awaitable, Callable
from typing import Any

from backend.config import AppConfig, load_config
from backend.llm import generate_playlist_draft

LOGGER = logging.getLogger("playlistmuse.lastfm.enrichment")
MAX_ENRICHED_TRACKS = 12

PlaylistGenerator = Callable[[AppConfig, str, int], Awaitable[dict[str, Any]]]


def _normalize_identity(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value).casefold())
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[a-z0-9]+", without_marks))


def _candidate_key(candidate: dict[str, str]) -> tuple[str, str]:
    return (
        _normalize_identity(candidate.get("artist", "")),
        _normalize_identity(candidate.get("title", "")),
    )


def _enrichment_prompt(
    seed_artist: str,
    seed_title: str,
    candidates: list[dict[str, str]],
) -> str:
    exact_tracks = "\n".join(
        f"{index}. {candidate['artist']} — {candidate['title']}"
        for index, candidate in enumerate(candidates, start=1)
    )
    return (
        "Write editorial metadata for the exact existing songs listed below. "
        "Do not choose, add, remove, replace or reorder any song. Preserve every artist "
        "and title exactly as written. The playlist is inspired by "
        f"'{seed_title}' by {seed_artist}. For each listed song, write a concise audible "
        "description for 'About this track' and a specific explanation for 'Why it "
        "belongs here', relating it to the seed playlist's sound, mood, energy or flow. "
        f"Return exactly {len(candidates)} tracks.\n\nExact songs:\n{exact_tracks}"
    )


async def enrich_lastfm_candidates(
    seed_artist: str,
    seed_title: str,
    candidates: list[dict[str, str]],
    *,
    max_tracks: int = MAX_ENRICHED_TRACKS,
    config: AppConfig | None = None,
    generator: PlaylistGenerator | None = None,
) -> list[dict[str, str]]:
    """Replace generic Last.fm copy with AI-written editorial explanations.

    Candidate identity and ordering are preserved. Any provider failure or changed song
    identity falls back to the original Last.fm explanation so seed generation remains
    resilient.
    """
    enriched = [dict(candidate) for candidate in candidates]
    for candidate in enriched:
        candidate["source"] = "lastfm"

    selected = enriched[: min(max(0, max_tracks), len(enriched))]
    if not selected:
        return enriched

    active_config = config or load_config()
    if not active_config.configured:
        return enriched

    active_generator = generator or generate_playlist_draft
    try:
        draft = await active_generator(
            active_config,
            _enrichment_prompt(seed_artist, seed_title, selected),
            len(selected),
        )
    except Exception as error:  # Last.fm enrichment must never break generation.
        LOGGER.info("AI explanation enrichment for Last.fm tracks unavailable: %s", error)
        return enriched

    generated_by_key = {
        _candidate_key(track): track
        for track in draft.get("tracks", [])
        if isinstance(track, dict)
    }
    for candidate in selected:
        generated = generated_by_key.get(_candidate_key(candidate))
        if not generated:
            continue
        description = str(generated.get("description", "")).strip()
        reason = str(generated.get("reason", "")).strip()
        if description:
            candidate["description"] = description
        if reason:
            candidate["reason"] = reason

    return enriched
