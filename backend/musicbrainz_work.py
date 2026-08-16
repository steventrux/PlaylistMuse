"""Small cached MusicBrainz work-identity lookup used by temporal validation."""

from __future__ import annotations

import time
from typing import Any

import httpx

from backend.metadata_validation import API_ROOT
from backend.musicbrainz_client import rate_limited_get
from backend.version import USER_AGENT

_CACHE_TTL_SECONDS = 24 * 60 * 60
_CACHE_MAX_ITEMS = 512
_CACHE: dict[str, tuple[float, frozenset[str]]] = {}


def _prune_cache(now: float) -> None:
    expired = [key for key, value in _CACHE.items() if value[0] <= now]
    for key in expired:
        _CACHE.pop(key, None)
    while len(_CACHE) >= _CACHE_MAX_ITEMS:
        _CACHE.pop(next(iter(_CACHE)))


def _work_ids(payload: Any) -> frozenset[str]:
    if not isinstance(payload, dict):
        return frozenset()
    relations = payload.get("relations")
    if not isinstance(relations, list):
        return frozenset()
    values: set[str] = set()
    for relation in relations:
        if not isinstance(relation, dict):
            continue
        work = relation.get("work")
        if not isinstance(work, dict):
            continue
        work_id = str(work.get("id") or "").strip()
        if work_id:
            values.add(work_id)
    return frozenset(values)


async def recording_work_ids(
    recording_mbid: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> frozenset[str]:
    """Return MusicBrainz work IDs linked to a recording; unavailable data is neutral."""
    mbid = str(recording_mbid or "").strip()
    if not mbid:
        return frozenset()

    now = time.monotonic()
    _prune_cache(now)
    cached = _CACHE.get(mbid)
    if cached and cached[0] > now:
        return cached[1]

    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(8.0),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    result = frozenset()
    try:
        response = await rate_limited_get(
            active_client,
            f"{API_ROOT}/recording/{mbid}",
            params={"fmt": "json", "inc": "work-rels"},
        )
        response.raise_for_status()
        result = _work_ids(response.json())
    except (httpx.HTTPError, ValueError, TypeError):
        result = frozenset()
    finally:
        if owns_client:
            await active_client.aclose()

    _prune_cache(time.monotonic())
    _CACHE[mbid] = (time.monotonic() + _CACHE_TTL_SECONDS, result)
    return result


def _clear_cache() -> None:
    _CACHE.clear()
