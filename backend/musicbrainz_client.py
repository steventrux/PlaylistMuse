"""Shared MusicBrainz request scheduling for all metadata subsystems."""

from __future__ import annotations

import asyncio
import threading
import time

import httpx

_REQUEST_INTERVAL_SECONDS = 1.05
_SCHEDULE_LOCK = threading.Lock()
_NEXT_REQUEST_AT = 0.0


async def rate_limited_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, str],
) -> httpx.Response:
    """Start MusicBrainz requests at a process-wide, rate-limited cadence."""
    global _NEXT_REQUEST_AT

    now = time.monotonic()
    with _SCHEDULE_LOCK:
        scheduled_at = max(now, _NEXT_REQUEST_AT)
        _NEXT_REQUEST_AT = scheduled_at + _REQUEST_INTERVAL_SECONDS

    delay = scheduled_at - now
    if delay > 0:
        await asyncio.sleep(delay)
    return await client.get(url, params=params)
