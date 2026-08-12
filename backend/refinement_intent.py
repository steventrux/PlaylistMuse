"""Normalize high-level Playlist Studio edit intents before refinement."""

from __future__ import annotations

import re

from backend.artist_quota_detection import (
    artist_matches,
    extract_artist_minimum_quotas,
)
from backend.refinement_targets import ArtistAdditionTarget, extract_artist_addition_targets

_ADDITION_INTENT_RE = re.compile(
    r"\b(?:add|include|insert|aggiungi|aggiungere|inserisci|inserire|includi|includere|"
    r"añade|anade|agrega|agregar|incluye|incluir|ajoute|ajouter|inclus|inclure|"
    r"füge|fuege|hinzufügen|hinzufuegen)\b",
    re.IGNORECASE,
)


def _merge_targets(
    primary: list[ArtistAdditionTarget],
    additions: list[ArtistAdditionTarget],
) -> list[ArtistAdditionTarget]:
    merged = list(primary)
    for target in additions:
        existing_index = next(
            (
                index
                for index, existing in enumerate(merged)
                if artist_matches(existing.artist, target.artist)
                or artist_matches(target.artist, existing.artist)
            ),
            None,
        )
        if existing_index is None:
            merged.append(target)
            continue
        existing = merged[existing_index]
        if target.count > existing.count:
            merged[existing_index] = ArtistAdditionTarget(existing.artist, target.count)
    return merged


def studio_artist_addition_targets(instruction: str) -> list[ArtistAdditionTarget]:
    """Return exact incremental additions, including compact multi-artist forms."""
    explicit = extract_artist_addition_targets(instruction)
    if not _ADDITION_INTENT_RE.search(instruction):
        return explicit

    compact = [
        ArtistAdditionTarget(quota.artist, quota.minimum)
        for quota in extract_artist_minimum_quotas(instruction)
    ]
    return _merge_targets(explicit, compact)


def studio_addition_guidance(targets: list[ArtistAdditionTarget]) -> str:
    """Append parser-friendly exact additions without changing the user's original text."""
    if not targets:
        return ""
    requirements = "\n".join(
        f"Add {target.count} tracks by {target.artist}." for target in targets
    )
    return (
        "\n\nNORMALIZED PLAYLIST STUDIO ADDITIONS:\n"
        f"{requirements}\n"
        "These are exact NEW-track additions. Keep the playlist size unchanged by replacing "
        "only the required number of editable tracks."
    )
