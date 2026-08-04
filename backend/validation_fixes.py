"""Prompt parsing and provider-message validation safeguards."""

from __future__ import annotations

import re
from functools import wraps
from typing import Any, Callable

_QUOTA_CLAUSE_SEPARATOR_RE = re.compile(
    r"[,;]\s*(?=(?:(?:almeno|minimo|min\.|at\s+least|minimum(?:\s+of)?)\s+)?"
    r"\d{1,3}\s+(?:canzoni|brani|tracce|pezzi|songs|tracks)\b)",
    re.IGNORECASE,
)


def temporal_assessment(prompt: str) -> Any | None:
    """Reject true temporal intersections, not unions of multiple periods."""
    from backend import prompt_validation as module

    decade_matches = list(module._DECADE_RE.finditer(prompt))
    range_matches = list(module._RANGE_RE.finditer(prompt))
    if len(decade_matches) + len(range_matches) > 1:
        return None

    lower_bounds: list[int] = []
    upper_bounds: list[int] = []
    for match in decade_matches:
        value = match.group(1) or match.group(2)
        lower, upper = module._decade_bounds(value)
        lower_bounds.append(lower)
        upper_bounds.append(upper)
    for match in range_matches:
        first, second = sorted((int(match.group(1)), int(match.group(2))))
        lower_bounds.append(first)
        upper_bounds.append(second)

    lower_bounds.extend(
        int(match.group(1)) + 1
        for match in module._AFTER_RE.finditer(prompt)
    )
    lower_bounds.extend(
        int(match.group(1))
        for match in module._FROM_ONWARD_RE.finditer(prompt)
    )
    upper_bounds.extend(
        int(match.group(1)) - 1
        for match in module._BEFORE_RE.finditer(prompt)
    )
    upper_bounds.extend(
        int(match.group(1))
        for match in module._UNTIL_RE.finditer(prompt)
    )

    if not lower_bounds or not upper_bounds:
        return None
    effective_lower = max(lower_bounds)
    effective_upper = min(upper_bounds)
    if effective_lower <= effective_upper:
        return None

    if module._ITALIAN_HINT_RE.search(prompt):
        reason = (
            "I vincoli temporali sono incompatibili: richiedono contemporaneamente "
            f"brani non precedenti al {effective_lower} e non successivi al {effective_upper}."
        )
    else:
        reason = (
            "The date constraints are incompatible: they require tracks released no earlier "
            f"than {effective_lower} and no later than {effective_upper}."
        )
    return module.PromptAssessment(status="impossible", reasons=(reason,))


def quota_extractor(
    original: Callable[[str], list[Any]],
) -> Callable[[str], list[Any]]:
    """Accept comma and semicolon separators between numeric artist quotas."""

    @wraps(original)
    def extract(prompt: str) -> list[Any]:
        from backend.artist_quota_detection import user_request_text

        request = user_request_text(prompt)
        normalized = _QUOTA_CLAUSE_SEPARATOR_RE.sub(" e ", request)
        return original(normalized)

    return extract


def safe_error_message(error: Exception) -> str:
    """Sanitize every provider error, including already wrapped provider errors."""
    from backend import llm as module

    text = str(error)
    text = module._URL_RE.sub("", text)
    text = module._API_KEY_RE.sub("[redacted]", text)
    text = module._QUERY_KEY_RE.sub("key=[redacted]", text)
    text = " ".join(text.split()).strip()
    message = text[:420] or "The AI provider could not complete the request."
    if message.startswith("The AI provider produced"):
        summary = message.split(".", 1)[0].strip()
        return f"{summary}. Try again or select another configured AI provider."
    return message
