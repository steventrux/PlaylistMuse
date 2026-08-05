"""Prompt parsing and provider-message validation safeguards."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable

_QUOTA_CLAUSE_SEPARATOR_RE = re.compile(
    r"[,;]\s*(?=(?:(?:almeno|minimo|min\.|at\s+least|minimum(?:\s+of)?)\s+)?"
    r"\d{1,3}\s+(?:canzoni|brani|tracce|pezzi|songs|tracks)\b)",
    re.IGNORECASE,
)
_TEMPORAL_UNION_RE = re.compile(
    r"(?:\b(?:e|o|oppure|and|or|et|ou|y|und|oder)\b|[/;])",
    re.IGNORECASE,
)
_YEAR_TOKEN = r"(?:\d{2}|19\d{2}|20\d{2})"
_TEMPORAL_RANGE_RE = re.compile(
    rf"\b(?:between|from|dal|dall['’]?|tra(?:\s+il)?|entre)\s*"
    rf"({_YEAR_TOKEN})\s*(?:and|e|to|al|a|et|y|-)\s*"
    rf"(?:(?:il|lo|la|the|le|el)\s+)?({_YEAR_TOKEN})\b",
    re.IGNORECASE,
)


def _expand_year(value: str) -> int:
    """Expand common two-digit years relative to the current century boundary."""
    year = int(value)
    if year >= 100:
        return year
    current_year = datetime.now(timezone.utc).year
    current_two_digits = current_year % 100
    century = current_year - current_two_digits
    return century + year if year <= current_two_digits else century - 100 + year


def _temporal_failure(
    module: Any,
    prompt: str,
    lower: int | None,
    upper: int | None,
) -> Any:
    if module._ITALIAN_HINT_RE.search(prompt):
        if lower is not None and upper is not None:
            reason = (
                "I vincoli temporali sono incompatibili: richiedono contemporaneamente "
                f"brani non precedenti al {lower} e non successivi al {upper}."
            )
        else:
            reason = (
                "I periodi e i limiti temporali richiesti non hanno alcuna "
                "sovrapposizione valida."
            )
    elif lower is not None and upper is not None:
        reason = (
            "The date constraints are incompatible: they require tracks released no earlier "
            f"than {lower} and no later than {upper}."
        )
    else:
        reason = "The requested periods and date limits have no valid overlap."
    return module.PromptAssessment(status="impossible", reasons=(reason,))


def _bounded_periods(module: Any, prompt: str) -> list[tuple[int, int, int, int]]:
    periods: list[tuple[int, int, int, int]] = []
    for match in module._DECADE_RE.finditer(prompt):
        value = match.group(1) or match.group(2)
        lower, upper = module._decade_bounds(value)
        periods.append((match.start(), match.end(), lower, upper))
    for match in _TEMPORAL_RANGE_RE.finditer(prompt):
        lower, upper = sorted(
            (_expand_year(match.group(1)), _expand_year(match.group(2)))
        )
        periods.append((match.start(), match.end(), lower, upper))
    return sorted(periods, key=lambda item: (item[0], item[1]))


def _combine_periods(
    prompt: str,
    periods: list[tuple[int, int, int, int]],
) -> tuple[list[tuple[int, int]], tuple[int, int] | None]:
    if not periods:
        return [], None

    _, previous_end, lower, upper = periods[0]
    alternatives = [(lower, upper)]
    contradiction: tuple[int, int] | None = None

    for start, end, next_lower, next_upper in periods[1:]:
        separator = prompt[previous_end:start]
        previous_end = end
        if _TEMPORAL_UNION_RE.search(separator):
            alternatives.append((next_lower, next_upper))
            continue

        intersected: list[tuple[int, int]] = []
        for current_lower, current_upper in alternatives:
            combined_lower = max(current_lower, next_lower)
            combined_upper = min(current_upper, next_upper)
            if combined_lower <= combined_upper:
                intersected.append((combined_lower, combined_upper))
            elif contradiction is None:
                contradiction = (combined_lower, combined_upper)
        alternatives = intersected
        if not alternatives:
            break

    return alternatives, contradiction


def effective_temporal_range(prompt: str) -> tuple[int, int] | None:
    """Return one exact interval only when all valid periods are contiguous."""
    from backend import prompt_validation as module

    periods = _bounded_periods(module, prompt)
    alternatives, _ = _combine_periods(prompt, periods)
    if not alternatives:
        return None

    lower_bounds = [
        int(match.group(1)) + 1
        for match in module._AFTER_RE.finditer(prompt)
    ]
    lower_bounds.extend(
        int(match.group(1))
        for match in module._FROM_ONWARD_RE.finditer(prompt)
    )
    upper_bounds = [
        int(match.group(1)) - 1
        for match in module._BEFORE_RE.finditer(prompt)
    ]
    upper_bounds.extend(
        int(match.group(1))
        for match in module._UNTIL_RE.finditer(prompt)
    )
    global_lower = max(lower_bounds) if lower_bounds else None
    global_upper = min(upper_bounds) if upper_bounds else None

    constrained: list[tuple[int, int]] = []
    for period_lower, period_upper in alternatives:
        lower = max(
            period_lower,
            global_lower if global_lower is not None else period_lower,
        )
        upper = min(
            period_upper,
            global_upper if global_upper is not None else period_upper,
        )
        if lower <= upper:
            constrained.append((lower, upper))
    if not constrained:
        return None

    ordered = sorted(constrained)
    merged_lower, merged_upper = ordered[0]
    for lower, upper in ordered[1:]:
        if lower > merged_upper + 1:
            return None
        merged_upper = max(merged_upper, upper)
    return merged_lower, merged_upper


def temporal_assessment(prompt: str) -> Any | None:
    """Validate unions of periods while intersecting additional date limits."""
    from backend import prompt_validation as module

    periods = _bounded_periods(module, prompt)
    alternatives, contradiction = _combine_periods(prompt, periods)
    if periods and not alternatives:
        lower, upper = contradiction or (None, None)
        return _temporal_failure(module, prompt, lower, upper)

    lower_bounds = [
        int(match.group(1)) + 1
        for match in module._AFTER_RE.finditer(prompt)
    ]
    lower_bounds.extend(
        int(match.group(1))
        for match in module._FROM_ONWARD_RE.finditer(prompt)
    )
    upper_bounds = [
        int(match.group(1)) - 1
        for match in module._BEFORE_RE.finditer(prompt)
    ]
    upper_bounds.extend(
        int(match.group(1))
        for match in module._UNTIL_RE.finditer(prompt)
    )

    global_lower = max(lower_bounds) if lower_bounds else None
    global_upper = min(upper_bounds) if upper_bounds else None
    if (
        global_lower is not None
        and global_upper is not None
        and global_lower > global_upper
    ):
        return _temporal_failure(
            module,
            prompt,
            global_lower,
            global_upper,
        )

    if not alternatives:
        return None

    constrained: list[tuple[int, int]] = []
    for period_lower, period_upper in alternatives:
        effective_lower = max(
            period_lower,
            global_lower if global_lower is not None else period_lower,
        )
        effective_upper = min(
            period_upper,
            global_upper if global_upper is not None else period_upper,
        )
        if effective_lower <= effective_upper:
            constrained.append((effective_lower, effective_upper))

    if constrained:
        return None

    if global_lower is not None and all(
        period_upper < global_lower for _, period_upper in alternatives
    ):
        return _temporal_failure(
            module,
            prompt,
            global_lower,
            max(period_upper for _, period_upper in alternatives),
        )
    if global_upper is not None and all(
        period_lower > global_upper for period_lower, _ in alternatives
    ):
        return _temporal_failure(
            module,
            prompt,
            min(period_lower for period_lower, _ in alternatives),
            global_upper,
        )
    return _temporal_failure(module, prompt, global_lower, global_upper)


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
