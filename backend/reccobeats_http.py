"""Shared, rate-safe HTTP access for ReccoBeats."""

from __future__ import annotations

import asyncio
import copy
import logging
import threading
import time
import weakref
from collections.abc import Callable
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

API_ROOT = "https://api.reccobeats.com/v1"
MAX_CONCURRENT_REQUESTS = 1
MIN_REQUEST_INTERVAL_SECONDS = 0.5
DEFAULT_RETRY_AFTER_SECONDS = 3.0
MAX_RETRY_AFTER_SECONDS = 120.0
CACHE_MAX_ENTRIES = 2048
SEARCH_CACHE_TTL_SECONDS = 6 * 60 * 60
TRACK_CACHE_TTL_SECONDS = 60 * 60
RECOMMENDATION_CACHE_TTL_SECONDS = 30 * 60
AUDIO_CACHE_TTL_SECONDS = 6 * 60 * 60

LOGGER = logging.getLogger("playlistmuse.performance")
_STATE_LOCK = threading.Lock()
_BLOCKED_UNTIL = 0.0
_NEXT_REQUEST_AT = 0.0
_CACHE: dict[
    tuple[str, tuple[tuple[str, str], ...]],
    tuple[float, Any],
] = {}
_LOOP_SEMAPHORES: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop,
    asyncio.Semaphore,
] = weakref.WeakKeyDictionary()


class ReccoRateLimited(httpx.HTTPError):
    """Raised locally while ReccoBeats is inside a server-requested cooldown."""


def _cache_key(
    path: str,
    params: dict[str, Any] | None,
) -> tuple[str, tuple[tuple[str, str], ...]]:
    normalized = tuple(
        sorted((str(key), str(value)) for key, value in (params or {}).items())
    )
    return str(path), normalized


def _cache_ttl(path: str) -> float:
    normalized = str(path)
    if normalized == "/track":
        return TRACK_CACHE_TTL_SECONDS
    if normalized == "/track/recommendation":
        return RECOMMENDATION_CACHE_TTL_SECONDS
    if normalized.endswith("/audio-features"):
        return AUDIO_CACHE_TTL_SECONDS
    return SEARCH_CACHE_TTL_SECONDS


def _prune_cache(now: float) -> None:
    expired = [key for key, value in _CACHE.items() if value[0] <= now]
    for key in expired:
        _CACHE.pop(key, None)
    while len(_CACHE) >= CACHE_MAX_ENTRIES:
        _CACHE.pop(next(iter(_CACHE)))


def _cached_payload(
    key: tuple[str, tuple[tuple[str, str], ...]],
    now: float,
) -> Any | None:
    with _STATE_LOCK:
        cached = _CACHE.get(key)
        if cached is None or cached[0] <= now:
            if cached is not None:
                _CACHE.pop(key, None)
            return None
        return copy.deepcopy(cached[1])


def _store_payload(
    key: tuple[str, tuple[tuple[str, str], ...]],
    payload: Any,
    *,
    now: float,
    ttl: float,
) -> None:
    with _STATE_LOCK:
        _prune_cache(now)
        _CACHE[key] = (now + ttl, copy.deepcopy(payload))


def _loop_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    with _STATE_LOCK:
        semaphore = _LOOP_SEMAPHORES.get(loop)
        if semaphore is None:
            semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
            _LOOP_SEMAPHORES[loop] = semaphore
        return semaphore


def _retry_after_seconds(response: httpx.Response) -> float:
    raw = str(response.headers.get("Retry-After", "")).strip()
    if raw:
        try:
            value = float(raw)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(raw)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                value = retry_at.timestamp() - time.time()
            except (TypeError, ValueError, OverflowError):
                value = DEFAULT_RETRY_AFTER_SECONDS
    else:
        value = DEFAULT_RETRY_AFTER_SECONDS
    return min(MAX_RETRY_AFTER_SECONDS, max(0.5, value))


def _cooldown_remaining(now: float) -> float:
    with _STATE_LOCK:
        return max(0.0, _BLOCKED_UNTIL - now)


async def request_json(
    client: httpx.AsyncClient,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    now: Callable[[], float] = time.monotonic,
) -> Any:
    """GET one Recco endpoint with shared cache, pacing and a global 429 circuit breaker."""
    global _BLOCKED_UNTIL, _NEXT_REQUEST_AT

    key = _cache_key(path, params)
    current = now()
    cached = _cached_payload(key, current)
    if cached is not None:
        return cached

    remaining = _cooldown_remaining(current)
    if remaining > 0:
        raise ReccoRateLimited(
            f"ReccoBeats cooldown active for {remaining:.2f}s"
        )

    semaphore = _loop_semaphore()
    async with semaphore:
        current = now()
        cached = _cached_payload(key, current)
        if cached is not None:
            return cached

        remaining = _cooldown_remaining(current)
        if remaining > 0:
            raise ReccoRateLimited(
                f"ReccoBeats cooldown active for {remaining:.2f}s"
            )

        with _STATE_LOCK:
            delay = max(0.0, _NEXT_REQUEST_AT - current)
        if delay > 0:
            await asyncio.sleep(delay)

        current = now()
        with _STATE_LOCK:
            _NEXT_REQUEST_AT = current + MIN_REQUEST_INTERVAL_SECONDS

        response = await client.get(f"{API_ROOT}{path}", params=params)
        status_code = int(getattr(response, "status_code", 200))
        if status_code == 429:
            retry_after = _retry_after_seconds(response)
            with _STATE_LOCK:
                _BLOCKED_UNTIL = max(_BLOCKED_UNTIL, now() + retry_after)
            LOGGER.warning(
                "reccobeats_rate_limited path=%s retry_after=%.2f",
                path,
                retry_after,
            )
            raise ReccoRateLimited(
                f"ReccoBeats rate limited; retry after {retry_after:.2f}s"
            )

        response.raise_for_status()
        payload = response.json()
        _store_payload(
            key,
            payload,
            now=now(),
            ttl=_cache_ttl(path),
        )
        # payload was just parsed fresh above and isn't shared with anything else yet
        # (the cache holds its own deep copy), so it can be returned directly here.
        return payload


def clear_reccobeats_http_state() -> None:
    """Reset shared cache/cooldown state for deterministic unit tests."""
    global _BLOCKED_UNTIL, _NEXT_REQUEST_AT
    with _STATE_LOCK:
        _BLOCKED_UNTIL = 0.0
        _NEXT_REQUEST_AT = 0.0
        _CACHE.clear()
        _LOOP_SEMAPHORES.clear()
