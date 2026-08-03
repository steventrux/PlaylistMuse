"""Classify playlist prompts before generation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from backend.config import AppConfig
from backend.constraint_interpreter import interpret_constraints

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
    """Interpret and classify one playlist prompt, failing open on provider errors."""
    payload = await interpret_constraints(config, prompt)
    return assess_interpretation(payload)
