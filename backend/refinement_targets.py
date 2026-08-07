"""Deterministic targets for incremental playlist refinement instructions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.artist_quota_detection import artist_matches
from backend.youtube import track_identity_key

_TRACK_WORDS = (
    r"(?:songs?|tracks?|canzoni|brani|tracce|pezzi|canciones?|temas?|"
    r"chansons?|titres?|lieder|titel)"
)
_ADD_VERBS = (
    r"(?:add|include|insert|aggiungi|aggiungere|inserisci|inserire|includi|includere|"
    r"añade|anade|agrega|agregar|incluye|incluir|ajoute|ajouter|inclus|inclure|"
    r"füge|fuege|hinzufügen|hinzufuegen|nimm)"
)
_PREPOSITIONS = r"(?:by|from|di|dei|degli|delle|da|de|del|du|des|von)"
_OPTIONAL_NEW = (
    r"(?:(?:new|nuov[ei]|nuev[oa]s?|nouveaux|nouvelles?|neu(?:e|en)?)\s+)?"
)

_ADD_COUNT_TRACK_ARTIST_RE = re.compile(
    rf"\b{_ADD_VERBS}\b\s+(?P<count>\d{{1,3}})\s+{_OPTIONAL_NEW}"
    rf"{_TRACK_WORDS}\s+{_PREPOSITIONS}\s+(?P<artist>[^,;.!?\n]+)",
    re.IGNORECASE,
)
_ADD_COUNT_ARTIST_TRACK_RE = re.compile(
    rf"\b{_ADD_VERBS}\b\s+(?P<count>\d{{1,3}})\s+{_OPTIONAL_NEW}"
    rf"(?P<artist>[^,;.!?\n]+?)\s+{_TRACK_WORDS}\b",
    re.IGNORECASE,
)
_TRAILING_EDIT_CLAUSE_RE = re.compile(
    r"\s+(?:and|e|ed|y|et|und)\s+(?=(?:add|include|insert|remove|delete|drop|exclude|"
    r"aggiungi|inserisci|includi|rimuovi|elimina|togli|escludi|añade|anade|agrega|"
    r"incluye|quita|elimina|ajoute|inclus|retire|supprime|füge|fuege|entferne|"
    r"lösche|losche|reorder|order|sort|riordina|ordina|ordena|réorganise|reorganise|"
    r"ordonne|trie|sortiere|ordne|make|rendi|rendila|haz|rends|mache)\b).*$",
    re.IGNORECASE,
)
_TRAILING_GERMAN_HINZU_RE = re.compile(r"\s+hinzu\s*$", re.IGNORECASE)
_REORDER_INTENT_RE = re.compile(
    r"\b(?:reorder|re-order|rearrange|sort|sequence|order|"
    r"riordina|riordinare|ordina|ordinare|"
    r"reordena|reordenar|ordena|ordenar|"
    r"réorganise|reorganise|réorganiser|reorganiser|ordonne|ordonner|trie|trier|"
    r"sortiere|sortieren|ordne|ordnen|umsortiere|umsortieren)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ArtistAdditionTarget:
    """An exact number of new tracks to add for one artist."""

    artist: str
    count: int


def _clean_artist(value: str) -> str:
    text = " ".join(str(value).split()).strip(" \t\r\n.,;:!?\"'“”")
    text = _TRAILING_EDIT_CLAUSE_RE.sub("", text).strip()
    text = _TRAILING_GERMAN_HINZU_RE.sub("", text).strip()
    return text[:180]


def _equivalent_target_index(
    targets: list[ArtistAdditionTarget],
    artist: str,
) -> int | None:
    return next(
        (
            index
            for index, target in enumerate(targets)
            if artist_matches(target.artist, artist) or artist_matches(artist, target.artist)
        ),
        None,
    )


def extract_artist_addition_targets(instruction: str) -> list[ArtistAdditionTarget]:
    """Extract explicit `add N tracks by artist` targets in supported input languages."""
    positioned: list[tuple[int, ArtistAdditionTarget]] = []
    for pattern in (_ADD_COUNT_TRACK_ARTIST_RE, _ADD_COUNT_ARTIST_TRACK_RE):
        for match in pattern.finditer(instruction):
            artist = _clean_artist(match.group("artist"))
            if not artist:
                continue
            count = max(1, min(100, int(match.group("count"))))
            positioned.append((match.start(), ArtistAdditionTarget(artist, count)))

    targets: list[ArtistAdditionTarget] = []
    for _, target in sorted(positioned, key=lambda item: item[0]):
        existing_index = _equivalent_target_index(targets, target.artist)
        if existing_index is None:
            targets.append(target)
            continue
        existing = targets[existing_index]
        if target.count > existing.count:
            targets[existing_index] = ArtistAdditionTarget(existing.artist, target.count)
    return targets


def artist_addition_guidance(targets: list[ArtistAdditionTarget]) -> str:
    if not targets:
        return "- None"
    return "\n".join(
        f"- Add exactly {target.count} NEW distinct tracks by {target.artist}. Existing tracks "
        "by that artist do not count toward this addition target."
        for target in targets
    )


def _track_key(track: dict[str, Any]) -> str:
    return track_identity_key(
        str(track.get("title") or ""),
        str(track.get("artists") or track.get("artist") or ""),
    )


def artist_addition_counts(
    current_tracks: list[dict[str, Any]],
    refined_tracks: list[dict[str, Any]],
    targets: list[ArtistAdditionTarget],
) -> dict[str, int]:
    """Count only tracks newly introduced by this refinement for each target artist."""
    current_keys = {_track_key(track) for track in current_tracks if _track_key(track)}
    counts = {target.artist: 0 for target in targets}
    for track in refined_tracks:
        key = _track_key(track)
        if not key or key in current_keys:
            continue
        artist = str(track.get("artists") or track.get("artist") or "").strip()
        for target in targets:
            if artist_matches(artist, target.artist):
                counts[target.artist] += 1
    return counts


def artist_addition_mismatches(
    current_tracks: list[dict[str, Any]],
    refined_tracks: list[dict[str, Any]],
    targets: list[ArtistAdditionTarget],
) -> list[tuple[ArtistAdditionTarget, int]]:
    counts = artist_addition_counts(current_tracks, refined_tracks, targets)
    return [
        (target, counts[target.artist])
        for target in targets
        if counts[target.artist] != target.count
    ]


def format_artist_addition_mismatches(
    mismatches: list[tuple[ArtistAdditionTarget, int]],
) -> str:
    details = "; ".join(
        f"requested {target.count} new tracks by {target.artist}, resolved {actual}"
        for target, actual in mismatches
    )
    return "The refinement could not satisfy the explicit addition target: " + details + "."


def explicit_reorder_requested(instruction: str) -> bool:
    """Return whether the user explicitly requested ordering/rearrangement."""
    return bool(_REORDER_INTENT_RE.search(instruction))


def preserve_existing_positions(
    current_tracks: list[dict[str, Any]],
    refined_tracks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep retained tracks in their original slots and place new tracks only in vacated slots."""
    current_keys = {_track_key(track) for track in current_tracks if _track_key(track)}
    retained_by_key = {
        _track_key(track): track
        for track in refined_tracks
        if _track_key(track) in current_keys
    }
    additions = [
        track for track in refined_tracks if _track_key(track) not in current_keys
    ]
    addition_index = 0
    stable: list[dict[str, Any]] = []

    for current in current_tracks:
        key = _track_key(current)
        retained = retained_by_key.get(key)
        if retained is not None:
            stable.append(retained)
            continue
        if addition_index < len(additions):
            stable.append(additions[addition_index])
            addition_index += 1

    stable.extend(additions[addition_index:])
    return stable[: len(refined_tracks)]
