"""Classify playlist prompts before generation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from backend.config import AppConfig
from backend.constraint_interpreter import interpret_constraints
from backend.constraint_relationships import find_album_artist_conflict

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
    """Detect explicit date constraints whose intersection is empty."""
    lower_bounds: list[int] = []
    upper_bounds: list[int] = []

    for match in _DECADE_RE.finditer(prompt):
        value = match.group(1) or match.group(2)
        lower, upper = _decade_bounds(value)
        lower_bounds.append(lower)
        upper_bounds.append(upper)

    for match in _RANGE_RE.finditer(prompt):
        first, second = sorted((int(match.group(1)), int(match.group(2))))
        lower_bounds.append(first)
        upper_bounds.append(second)

    lower_bounds.extend(int(match.group(1)) + 1 for match in _AFTER_RE.finditer(prompt))
    lower_bounds.extend(int(match.group(1)) for match in _FROM_ONWARD_RE.finditer(prompt))
    upper_bounds.extend(int(match.group(1)) - 1 for match in _BEFORE_RE.finditer(prompt))
    upper_bounds.extend(int(match.group(1)) for match in _UNTIL_RE.finditer(prompt))

    if not lower_bounds or not upper_bounds:
        return None

    effective_lower = max(lower_bounds)
    effective_upper = min(upper_bounds)
    if effective_lower <= effective_upper:
        return None

    if _ITALIAN_HINT_RE.search(prompt):
        reason = (
            "I vincoli temporali sono incompatibili: richiedono contemporaneamente "
            f"brani non precedenti al {effective_lower} e non successivi al {effective_upper}."
        )
    else:
        reason = (
            "The date constraints are incompatible: they require tracks released no earlier "
            f"than {effective_lower} and no later than {effective_upper}."
        )
    return PromptAssessment(status="impossible", reasons=(reason,))


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


async def assess_prompt(config: AppConfig, prompt: str) -> PromptAssessment:
    """Classify local, interpreted and strongly verified cross-entity conflicts."""
    local_assessment = _local_temporal_assessment(prompt)
    if local_assessment is not None:
        return local_assessment

    payload = await interpret_constraints(config, prompt)
    assessment = assess_interpretation(payload)
    if assessment.status == "impossible" or not isinstance(payload, dict):
        return assessment

    relationship_conflict = await find_album_artist_conflict(payload)
    if relationship_conflict is not None:
        return _album_artist_conflict_assessment(
            prompt,
            relationship_conflict,
            payload,
        )
    return assessment
