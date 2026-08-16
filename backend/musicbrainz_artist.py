"""MusicBrainz artist-origin lookup with a small process TTL cache."""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from backend.musicbrainz_client import rate_limited_get
from backend.version import USER_AGENT

API_ROOT = "https://musicbrainz.org/ws/2"
CACHE_TTL_SECONDS = 90 * 24 * 60 * 60
NEGATIVE_TTL_SECONDS = 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class ArtistOrigin:
    country: str | None = None
    area: str | None = None


_CACHE: dict[str, tuple[float, ArtistOrigin]] = {}


def clear_artist_origin_cache() -> None:
    """Clear the in-process cache; intended for deterministic tests."""
    _CACHE.clear()


def _cache_get(artist_mbid: str) -> ArtistOrigin | None:
    cached = _CACHE.get(artist_mbid)
    if cached is None:
        return None
    expires_at, origin = cached
    if expires_at <= time.monotonic():
        _CACHE.pop(artist_mbid, None)
        return None
    return origin


def _cache_put(artist_mbid: str, origin: ArtistOrigin) -> None:
    ttl = CACHE_TTL_SECONDS if origin.country or origin.area else NEGATIVE_TTL_SECONDS
    _CACHE[artist_mbid] = (time.monotonic() + ttl, origin)


async def lookup_artist_origin(
    artist_mbid: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> ArtistOrigin | None:
    """Resolve one MusicBrainz artist MBID to country/area, failing open."""
    normalized_mbid = str(artist_mbid or "").strip().lower()
    if not normalized_mbid:
        return None

    cached = _cache_get(normalized_mbid)
    if cached is not None:
        return cached

    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(8.0),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        response = await rate_limited_get(
            active_client,
            f"{API_ROOT}/artist/{normalized_mbid}",
            params={"fmt": "json"},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("MusicBrainz artist response is not an object")

        area = payload.get("area") if isinstance(payload.get("area"), dict) else {}
        begin_area = (
            payload.get("begin-area")
            if isinstance(payload.get("begin-area"), dict)
            else {}
        )
        origin = ArtistOrigin(
            country=str(payload.get("country", "")).upper().strip() or None,
            area=str(area.get("name") or begin_area.get("name") or "").strip() or None,
        )
        _cache_put(normalized_mbid, origin)
        return origin
    except (httpx.HTTPError, ValueError, TypeError):
        return None
    finally:
        if owns_client:
            await active_client.aclose()
