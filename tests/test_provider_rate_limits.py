from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from backend import provider_rate_limits as rate_limits
from backend.provider_rate_limits import (
    FALLBACK_COOLDOWN_SECONDS,
    MAX_SHORT_COOLDOWN_SECONDS,
    clear_rate_limits,
    cooldown_seconds_for_response,
    format_cooldown,
    is_rate_limited,
    longest_remaining_cooldown,
    mark_rate_limited,
    seconds_remaining,
)

PACIFIC = ZoneInfo("America/Los_Angeles")


@pytest.fixture(autouse=True)
def _reset_cache():
    clear_rate_limits()
    yield
    clear_rate_limits()


def _gemini_response(status_code: int, quota_id: str, retry_delay: str) -> httpx.Response:
    return httpx.Response(
        status_code,
        json={
            "error": {
                "code": status_code,
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [{"quotaId": quota_id}],
                    },
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": retry_delay,
                    },
                ],
            }
        },
    )


def test_mark_and_check_round_trip() -> None:
    assert is_rate_limited("gemini", "gemini-3.6-flash") is False
    mark_rate_limited("gemini", "gemini-3.6-flash", cooldown_seconds=60)
    assert is_rate_limited("gemini", "gemini-3.6-flash") is True
    # A different model, or a different provider using the same model name, is unaffected.
    assert is_rate_limited("gemini", "gemini-3.7-flash") is False
    assert is_rate_limited("openai", "gemini-3.6-flash") is False


def test_rate_limit_expires_after_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"now": 1000.0}
    monkeypatch.setattr(rate_limits.time, "monotonic", lambda: clock["now"])

    mark_rate_limited("gemini", "gemini-3.6-flash", cooldown_seconds=30)
    assert is_rate_limited("gemini", "gemini-3.6-flash") is True

    clock["now"] += 31
    assert is_rate_limited("gemini", "gemini-3.6-flash") is False
    # Once expired, the entry is dropped rather than lingering forever.
    assert ("gemini", "gemini-3.6-flash") not in rate_limits._rate_limited_until


def test_clear_rate_limits_resets_everything() -> None:
    mark_rate_limited("gemini", "gemini-3.6-flash", cooldown_seconds=60)
    clear_rate_limits()
    assert is_rate_limited("gemini", "gemini-3.6-flash") is False


def test_daily_gemini_quota_cooldown_matches_seconds_until_pacific_midnight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        rate_limits, "_seconds_until_next_pacific_midnight", lambda now=None: 30_600.0
    )
    response = _gemini_response(
        429, "GenerateRequestsPerDayPerProjectPerModel-FreeTier", "24s"
    )

    cooldown = cooldown_seconds_for_response(response, "gemini")

    assert cooldown == 30_600.0  # the daily branch, NOT the 24s retryDelay hint


def test_seconds_until_next_pacific_midnight_is_exact() -> None:
    fixed_now = datetime(2026, 8, 14, 23, 0, 0, tzinfo=PACIFIC)
    seconds = rate_limits._seconds_until_next_pacific_midnight(fixed_now)
    assert seconds == pytest.approx(3600.0)

    just_before_midnight = datetime(2026, 8, 14, 23, 59, 59, tzinfo=PACIFIC)
    assert rate_limits._seconds_until_next_pacific_midnight(
        just_before_midnight
    ) == pytest.approx(1.0)


def test_per_minute_gemini_quota_uses_retry_delay_capped() -> None:
    response = _gemini_response(
        429, "GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "24s"
    )
    assert cooldown_seconds_for_response(response, "gemini") == 24.0

    long_response = _gemini_response(
        429, "GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "9999s"
    )
    assert cooldown_seconds_for_response(long_response, "gemini") == MAX_SHORT_COOLDOWN_SECONDS


def test_unrecognized_gemini_body_falls_back_to_fixed_cooldown() -> None:
    response = httpx.Response(429, json={"error": {"message": "unknown"}})
    assert cooldown_seconds_for_response(response, "gemini") == FALLBACK_COOLDOWN_SECONDS


def test_non_gemini_provider_respects_retry_after_header() -> None:
    response = httpx.Response(
        429, json={"error": "rate limited"}, headers={"retry-after": "42"}
    )
    assert cooldown_seconds_for_response(response, "anthropic") == 42.0


def test_non_gemini_provider_without_hints_falls_back() -> None:
    response = httpx.Response(429, json={"error": "rate limited"})
    assert cooldown_seconds_for_response(response, "anthropic") == FALLBACK_COOLDOWN_SECONDS


def test_seconds_remaining_is_none_until_marked() -> None:
    assert seconds_remaining("gemini", "gemini-3.6-flash") is None
    mark_rate_limited("gemini", "gemini-3.6-flash", cooldown_seconds=45)
    assert seconds_remaining("gemini", "gemini-3.6-flash") == pytest.approx(45, abs=1)


def test_longest_remaining_cooldown_requires_every_model_to_be_limited() -> None:
    mark_rate_limited("custom", "model-a", cooldown_seconds=10)
    # model-b is not rate-limited, so at least one model is still usable.
    assert longest_remaining_cooldown("custom", ["model-a", "model-b"]) is None

    mark_rate_limited("custom", "model-b", cooldown_seconds=90)
    assert longest_remaining_cooldown("custom", ["model-a", "model-b"]) == pytest.approx(
        90, abs=1
    )


def test_longest_remaining_cooldown_with_no_models_is_none() -> None:
    assert longest_remaining_cooldown("custom", []) is None


def test_format_cooldown_switches_to_minutes() -> None:
    assert format_cooldown(48) == "48s"
    assert format_cooldown(90) == "1m 30s"
    assert format_cooldown(120) == "2m"
