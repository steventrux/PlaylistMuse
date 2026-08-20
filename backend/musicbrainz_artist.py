"""MusicBrainz artist-origin lookup with a persistent on-disk TTL cache."""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

import httpx

from backend import cache_metrics
from backend.musicbrainz_client import rate_limited_get
from backend.version import USER_AGENT

API_ROOT = "https://musicbrainz.org/ws/2"
CACHE_TTL_SECONDS = 90 * 24 * 60 * 60
NEGATIVE_TTL_SECONDS = 24 * 60 * 60
PURGE_INTERVAL_SECONDS = 3600

_last_purge_at = 0.0


@dataclass(frozen=True, slots=True)
class ArtistOrigin:
    country: str | None = None
    area: str | None = None


def _cache_path() -> Path:
    root = Path(os.getenv("PLAYLISTMUSE_DATA_DIR", "data"))
    return root / "musicbrainz_artist_cache.sqlite3"


def _connect() -> sqlite3.Connection:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS artist_origin_cache (
            artist_mbid TEXT PRIMARY KEY,
            country TEXT,
            area TEXT,
            expires_at REAL NOT NULL
        )
        """
    )
    return connection


def clear_artist_origin_cache() -> None:
    """Clear the on-disk cache; intended for deterministic tests."""
    with suppress(OSError, sqlite3.Error), _connect() as connection:
        connection.execute("DELETE FROM artist_origin_cache")


def _cache_get(artist_mbid: str) -> ArtistOrigin | None:
    try:
        with _connect() as connection:
            row = connection.execute(
                "SELECT country, area, expires_at FROM artist_origin_cache "
                "WHERE artist_mbid = ?",
                (artist_mbid,),
            ).fetchone()
    except (OSError, sqlite3.Error):
        return None
    if not row or float(row["expires_at"]) <= time.time():
        cache_metrics.record_miss("MusicBrainz artist origin")
        return None
    cache_metrics.record_hit("MusicBrainz artist origin")
    return ArtistOrigin(country=row["country"], area=row["area"])


def _cache_put(artist_mbid: str, origin: ArtistOrigin) -> None:
    global _last_purge_at
    ttl = CACHE_TTL_SECONDS if origin.country or origin.area else NEGATIVE_TTL_SECONDS
    try:
        with _connect() as connection:
            connection.execute(
                """
                INSERT INTO artist_origin_cache(artist_mbid, country, area, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(artist_mbid) DO UPDATE SET
                  country = excluded.country,
                  area = excluded.area,
                  expires_at = excluded.expires_at
                """,
                (artist_mbid, origin.country, origin.area, time.time() + ttl),
            )
            now = time.time()
            if now - _last_purge_at > PURGE_INTERVAL_SECONDS:
                connection.execute(
                    "DELETE FROM artist_origin_cache WHERE expires_at <= ?", (now,)
                )
                _last_purge_at = now
    except (OSError, sqlite3.Error):
        return


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
