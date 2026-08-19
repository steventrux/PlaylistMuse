"""Classify playlist prompts before generation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from backend.config import AppConfig
from backend.constraint_interpreter import interpret_constraints
from backend.constraint_relationships import find_album_artist_conflict
from backend.text_normalization import normalize_identity

PromptStatus = Literal["valid", "ambiguous", "impossible"]

_STATUS_VALUES: set[str] = {"valid", "ambiguous", "impossible"}
_IMPOSSIBLE_HINT_RE = re.compile(
    r"\b(?:impossible|incompatible|mutually exclusive|no overlap|cannot both|"
    r"impossibile|incompatibil|senza sovrapposizione|non possono coesistere|"
    r"imposible|incompatible|sin superposici[oó]n|"
    r"impossible|incompatible|sans chevauchement|"
    r"unm[oö]glich|unvereinbar|kein[e]? [uü]berschneidung)\b",
    re.IGNORECASE,
)
_DECADE_RE = re.compile(
    r"\b(?:anni|années|años|anos|jahre|decade|décennie|década)\s*['’]?(\d{2}|19\d0|20\d0)\b|"
    r"\b(19\d0|20\d0)s\b",
    re.IGNORECASE,
)
_RANGE_RE = re.compile(
    r"\b(?:between|from|dal|dall['’]?|tra(?:\s+il)?|entre)\s*"
    r"(19\d{2}|20\d{2})\s*(?:and|e|to|al|a|et|y|-)\s*"
    r"(?:(?:il|l['’]?|the|le|la|el)\s*)?"
    r"(19\d{2}|20\d{2})\b",
    re.IGNORECASE,
)
_AFTER_RE = re.compile(
    r"\b(?:after|dopo(?:\s+il)?|après|apres|nach|después\s+de|despues\s+de)\s*"
    r"(19\d{2}|20\d{2})\b",
    re.IGNORECASE,
)
_FROM_ONWARD_RE = re.compile(
    r"\b(?:from|dal|a\s+partire\s+dal|desde)\s*"
    r"(19\d{2}|20\d{2})\s*(?:onward|onwards|in\s+poi|en\s+adelante)\b",
    re.IGNORECASE,
)
_BEFORE_RE = re.compile(
    r"\b(?:before|prima\s+del|avant|vor|antes\s+de)\s*"
    r"(19\d{2}|20\d{2})\b",
    re.IGNORECASE,
)
_UNTIL_RE = re.compile(
    r"\b(?:until|through|fino\s+al|jusqu['’]?à|jusqu['’]?a|bis|hasta)\s*"
    r"(19\d{2}|20\d{2})\b",
    re.IGNORECASE,
)
_ITALIAN_HINT_RE = re.compile(
    r"\b(?:musica|brani|canzoni|anni|dopo|prima|pubblicat[oaie]|dal|fino|"
    r"includi|escludi|album)\b",
    re.IGNORECASE,
)
_INCLUDED_ALBUM_RE = re.compile(
    r"\b(?:includi|inserisci|include|add)\s+(?:l['’]?album\s+|album\s+)?"
    r"[\"“”']?([^,;.!\n]{1,180}?)[\"“”']?(?=\s*(?:[,;.!\n]|$))",
    re.IGNORECASE,
)
_EXCLUDED_ARTIST_RE = re.compile(
    r"\b(?:escludi|senza|exclude|excluding|no)\s+(?:i|gli|le|l['’]?|the)?\s*"
    r"([^,;.!\n]{1,180}?)(?=\s*(?:[,;.!\n]|$))",
    re.IGNORECASE,
)


@dataclass(slots=True, frozen=True)
class PromptAssessment:
    status: PromptStatus
    reasons: tuple[str, ...] = ()
    interpretation: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reasons": list(self.reasons),
        }


def _clean_reasons(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    cleaned: list[str] = []
    for item in value[:8]:
        text = " ".join(str(item).split()).strip()
        if text and text not in cleaned:
            cleaned.append(text[:500])
    return tuple(cleaned)


def _status_from_payload(payload: dict[str, Any]) -> PromptStatus:
    raw_status = str(payload.get("constraint_status", "")).strip().casefold()
    if raw_status in _STATUS_VALUES:
        return raw_status  # type: ignore[return-value]

    contradictions = _clean_reasons(payload.get("contradictions"))
    if not contradictions:
        return "valid"
    if any(_IMPOSSIBLE_HINT_RE.search(reason) for reason in contradictions):
        return "impossible"
    return "ambiguous"


def _decade_bounds(value: str) -> tuple[int, int]:
    decade = int(value)
    if decade < 100:
        decade += 1900
    return decade, decade + 9


def _local_temporal_assessment(prompt: str) -> PromptAssessment | None:
    """Validate temporal unions and intersections deterministically."""
    from backend.validation_fixes import temporal_assessment

    return temporal_assessment(prompt)


def _clean_local_entity(value: str) -> str:
    cleaned = " ".join(value.split()).strip(" \t\r\n.,;:!?\"'“”")
    return cleaned[:180]


def _append_unique(values: Any, additions: list[str]) -> list[str]:
    current = [str(item).strip() for item in values] if isinstance(values, list) else []
    seen = {normalize_identity(item) for item in current if normalize_identity(item)}
    for addition in additions:
        key = normalize_identity(addition)
        if key and key not in seen:
            current.append(addition)
            seen.add(key)
    return current


def _augment_explicit_entity_constraints(
    prompt: str,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge only explicit album inclusions and artist exclusions found locally."""
    result = dict(payload) if isinstance(payload, dict) else {}
    albums = [
        cleaned
        for match in _INCLUDED_ALBUM_RE.finditer(prompt)
        if (cleaned := _clean_local_entity(match.group(1)))
    ]
    excluded_artists = [
        cleaned
        for match in _EXCLUDED_ARTIST_RE.finditer(prompt)
        if (cleaned := _clean_local_entity(match.group(1)))
    ]
    if albums:
        result["allowed_albums"] = _append_unique(result.get("allowed_albums"), albums)
    if excluded_artists:
        result["excluded_artists"] = _append_unique(
            result.get("excluded_artists"), excluded_artists
        )
    return result


def _album_artist_conflict_assessment(
    prompt: str,
    conflict: tuple[str, str],
    payload: dict[str, Any],
) -> PromptAssessment:
    album, artist = conflict
    if _ITALIAN_HINT_RE.search(prompt):
        reason = (
            f"La richiesta è impossibile: l’album “{album}” è attribuito a {artist}, "
            f"ma {artist} è esplicitamente escluso."
        )
    else:
        reason = (
            f'The request is impossible: the album “{album}” is credited to {artist}, '
            f"but {artist} is explicitly excluded."
        )
    return PromptAssessment(
        status="impossible",
        reasons=(reason,),
        interpretation=payload,
    )


def assess_interpretation(payload: dict[str, Any] | None) -> PromptAssessment:
    if not isinstance(payload, dict):
        return PromptAssessment(status="valid")

    status = _status_from_payload(payload)
    reasons = _clean_reasons(payload.get("status_reasons"))
    if not reasons:
        reasons = _clean_reasons(payload.get("contradictions"))
    if status != "valid" and not reasons:
        reasons = (
            "The request contains constraints that cannot be interpreted consistently."
            if status == "ambiguous"
            else "The request contains mutually incompatible constraints.",
        )
    return PromptAssessment(status=status, reasons=reasons, interpretation=payload)


_FAVORITES_MENTION_RE = re.compile(
    r"favorit|favourite|preferit|favoris|préfér|prefere|lieblings", re.IGNORECASE
)
# The AI's own ambiguity reason doesn't reliably echo back "favorite"/"preferiti" even
# when the ambiguity IS about missing artist identity (e.g. it may just say "no artist
# specified in the request") -- an artist-identity reason is included too whenever the
# *source prompt itself* explicitly asked for favorites (checked in the caller), since
# that's the only case this resolves.
_ARTIST_MENTION_RE = re.compile(r"artist|artiste|künstler", re.IGNORECASE)


def _suppress_resolvable_favorites_ambiguity(
    assessment: PromptAssessment, prompt: str
) -> PromptAssessment:
    """Drop ambiguity reasons the app can actually resolve from bookmarked favorites.

    `interpret_constraints()` has no visibility into this installation's saved
    favorites (backend/favorites.py), so it correctly flags "my favorite artists"
    as unresolvable from its own narrow perspective -- but the app does know which
    artists/tracks are meant. This is a post-filter, not a change to the cached LLM
    call, so it needs no cache-key changes.
    """
    if assessment.status != "ambiguous" or not assessment.reasons:
        return assessment

    from backend.favorites import (
        favorite_artist_names,
        favorite_categories_explicitly_requested,
        favorite_track_summaries,
    )

    explicit_artists, explicit_tracks = favorite_categories_explicitly_requested(prompt)
    if not explicit_artists and not explicit_tracks:
        return assessment
    if not favorite_artist_names(limit=1) and not favorite_track_summaries(limit=1):
        return assessment

    def _resolved_by_favorites(reason: str) -> bool:
        if _FAVORITES_MENTION_RE.search(reason):
            return True
        return explicit_artists and bool(_ARTIST_MENTION_RE.search(reason))

    kept = tuple(reason for reason in assessment.reasons if not _resolved_by_favorites(reason))
    if kept == assessment.reasons:
        return assessment
    return PromptAssessment(
        status="valid" if not kept else "ambiguous",
        reasons=kept,
        interpretation=assessment.interpretation,
    )


async def assess_prompt(config: AppConfig, prompt: str) -> PromptAssessment:
    """Classify local, interpreted and strongly verified cross-entity conflicts."""
    return _suppress_resolvable_favorites_ambiguity(
        await _assess_prompt_uncached(config, prompt), prompt
    )


async def _assess_prompt_uncached(config: AppConfig, prompt: str) -> PromptAssessment:
    local_assessment = _local_temporal_assessment(prompt)
    if local_assessment is not None:
        return local_assessment

    interpreted = await interpret_constraints(config, prompt)
    assessment = assess_interpretation(interpreted)
    if assessment.status == "impossible":
        return assessment

    payload = _augment_explicit_entity_constraints(prompt, interpreted)
    relationship_conflict = await find_album_artist_conflict(payload)
    if relationship_conflict is not None:
        return _album_artist_conflict_assessment(
            prompt,
            relationship_conflict,
            payload,
        )
    return PromptAssessment(
        status=assessment.status,
        reasons=assessment.reasons,
        interpretation=payload,
    )
