"""In-process cache of AI provider/model combinations known to be rate-limited.

Gemini's 429 responses expose a structured quota violation (see
``cooldown_seconds_for_response``) that lets us distinguish a short-lived per-minute/
per-second throttle from a terminal daily quota that will not recover until Google's own
reset time -- naively retrying a daily-exhausted model every few seconds (as its own
``retryDelay`` hint can suggest) just repeats the same wasted round trip.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger("playlistmuse.performance")

# Used only when a 429 carries no structured/standard hint we can trust.
FALLBACK_COOLDOWN_SECONDS = 300.0
# Ceiling for short-lived hints (Gemini per-minute/second retryDelay, or a Retry-After
# header) -- a provider reporting something absurdly long here is not trusted blindly.
MAX_SHORT_COOLDOWN_SECONDS = 300.0
# Gemini's requests-per-day quota resets at midnight Pacific time.
_GEMINI_RESET_TIMEZONE = ZoneInfo("America/Los_Angeles")
_RETRY_DELAY_RE = re.compile(r"([\d.]+)\s*s")

_rate_limited_until: dict[tuple[str, str], float] = {}


class ProviderRateLimitedError(Exception):
    """Raised when a model is skipped because it is cached as rate-limited."""


def _seconds_until_next_pacific_midnight(now: datetime | None = None) -> float:
    current = now or datetime.now(_GEMINI_RESET_TIMEZONE)
    if current.tzinfo is None:
        current = current.replace(tzinfo=_GEMINI_RESET_TIMEZONE)
    next_midnight = (current + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(1.0, (next_midnight - current).total_seconds())


def _gemini_error_details(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    error = payload.get("error")
    if not isinstance(error, dict):
        return []
    details = error.get("details")
    return [item for item in details if isinstance(item, dict)] if isinstance(details, list) else []


def _gemini_quota_ids(payload: Any) -> list[str]:
    """Return every quotaId from a Gemini QuotaFailure error detail, if present."""
    quota_ids: list[str] = []
    for detail in _gemini_error_details(payload):
        violations = detail.get("violations")
        if not isinstance(violations, list):
            continue
        for violation in violations:
            if isinstance(violation, dict):
                quota_id = str(violation.get("quotaId", "")).strip()
                if quota_id:
                    quota_ids.append(quota_id)
    return quota_ids


def _gemini_retry_delay_seconds(payload: Any) -> float | None:
    """Return Gemini's own RetryInfo.retryDelay in seconds, if present and parsable."""
    for detail in _gemini_error_details(payload):
        raw_delay = detail.get("retryDelay")
        if not isinstance(raw_delay, str):
            continue
        match = _RETRY_DELAY_RE.match(raw_delay.strip())
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                continue
    return None


def cooldown_seconds_for_response(response: httpx.Response, provider: str) -> float:
    """Return how long this provider/response says to wait before retrying this model.

    Prefers structured, verifiable signals over guessing: Gemini's own quota-violation type
    (daily vs. per-minute/per-second) when available, then the standard Retry-After header,
    then a conservative fixed fallback.
    """
    if provider == "gemini":
        try:
            payload = response.json()
        except ValueError:
            payload = None
        quota_ids = _gemini_quota_ids(payload)
        if any("day" in quota_id.casefold() for quota_id in quota_ids):
            return _seconds_until_next_pacific_midnight()
        if any(
            "minute" in quota_id.casefold() or "second" in quota_id.casefold()
            for quota_id in quota_ids
        ):
            retry_delay = _gemini_retry_delay_seconds(payload)
            if retry_delay is not None:
                return min(max(retry_delay, 1.0), MAX_SHORT_COOLDOWN_SECONDS)

    retry_after = response.headers.get("retry-after")
    if retry_after:
        try:
            return min(max(float(retry_after), 1.0), MAX_SHORT_COOLDOWN_SECONDS)
        except ValueError:
            pass

    return FALLBACK_COOLDOWN_SECONDS


def mark_rate_limited(provider: str, model: str, *, cooldown_seconds: float) -> None:
    expires_at = time.monotonic() + max(1.0, cooldown_seconds)
    _rate_limited_until[(provider, model)] = expires_at
    logger.info(
        "provider_rate_limit_cached provider=%s model=%s cooldown_seconds=%.0f",
        provider,
        model,
        cooldown_seconds,
    )


def is_rate_limited(provider: str, model: str) -> bool:
    expires_at = _rate_limited_until.get((provider, model))
    if expires_at is None:
        return False
    if expires_at <= time.monotonic():
        del _rate_limited_until[(provider, model)]
        return False
    logger.info(
        "provider_rate_limit_skip provider=%s model=%s remaining_seconds=%.0f",
        provider,
        model,
        expires_at - time.monotonic(),
    )
    return True


def clear_rate_limits() -> None:
    """Test-only: reset all cached rate-limit state."""
    _rate_limited_until.clear()
