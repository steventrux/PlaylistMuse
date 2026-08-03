"""Cross-entity validation for interpreted playlist constraints."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx

from backend.text_normalization import normalize_identity

API_ROOT = "https://musicbrainz.org/ws/2"
USER_AGENT = "PlaylistMuse/0.7 (https://github.com/steventrux/PlaylistMuse)"
CACHE_TTL_SECONDS = 180 * 24 * 60 * 60
MIN_API_SCORE = 90
MAX_ALBUMS_PER_REQUEST = 8
_REQUEST_LOCK = asyncio.Lock()
_LAST_REQUEST_AT = 0.0


def _cache_path() -> Path:
    root = Path(os.getenv("PLAYLISTMUSE_DATA_DIR", "data"))
    return root / "constraint_relationship_cache.sqlite3"


def _connect() -> sqlite3.Connection:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS album_artist_relationship_cache (
            normalized_album TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            expires_at REAL NOT NULL
        )
        """
    )
    return connection


def _read_cache(album: str) -> dict[str, Any] | None:
    key = normalize_identity(album)
    if not key:
        return None
    try:
        with _connect() as connection:
            row = connection.execute(
                "SELECT payload, expires_at FROM album_artist_relationship_cache "
                "WHERE normalized_album = ?",
                (key,),
            ).fetchone()
            if not row:
                return None
            if float(row["expires_at"]) <= time.time():
                connection.execute(
                    "DELETE FROM album_artist_relationship_cache WHERE normalized_album = ?",
                    (key,),
                )
                return None
            payload = json.loads(str(row["payload"]))
            return payload if isinstance(payload, dict) else None
    except (sqlite3.Error, ValueError, TypeError, json.JSONDecodeError):
        return None


def _write_cache(album: str, payload: dict[str, Any]) -> None:
    key = normalize_identity(album)
    if not key:
        return
    try:
        with _connect() as connection:
            connection.execute(
                """
                INSERT INTO album_artist_relationship_cache(
                    normalized_album, payload, expires_at
                ) VALUES (?, ?, ?)
                ON CONFLICT(normalized_album) DO UPDATE SET
                    payload = excluded.payload,
                    expires_at = excluded.expires_at
                """,
                (
                    key,
                    json.dumps(payload, ensure_ascii=False),
                    time.time() + CACHE_TTL_SECONDS,
                ),
            )
    except (sqlite3.Error, TypeError, ValueError):
        return


def _artist_credit_names(item: dict[str, Any]) -> list[str]:
    credits = item.get("artist-credit")
    if not isinstance(credits, list):
        return []
    names: list[str] = []
    for credit in credits:
        if not isinstance(credit, dict):
            continue
        artist = credit.get("artist")
        name = ""
        if isinstance(artist, dict):
            name = str(artist.get("name", "")).strip()
        if not name:
            name = str(credit.get("name", "")).strip()
        if name and name not in names:
            names.append(name)
    return names


async def _lookup_album_artists(album: str, client: httpx.AsyncClient) -> dict[str, Any]:
    global _LAST_REQUEST_AT
    cached = _read_cache(album)
    if cached is not None:
        return cached

    async with _REQUEST_LOCK:
        delay = 1.05 - (time.monotonic() - _LAST_REQUEST_AT)
        if delay > 0:
            await asyncio.sleep(delay)
        response = await client.get(
            f"{API_ROOT}/release-group",
            params={
                "query": f'releasegroup:"{album}"',
                "fmt": "json",
                "limit": "8",
            },
        )
        _LAST_REQUEST_AT = time.monotonic()
    response.raise_for_status()

    expected = normalize_identity(album)
    candidates = [
        item
        for item in response.json().get("release-groups", [])
        if isinstance(item, dict)
        and normalize_identity(str(item.get("title", ""))) == expected
        and int(item.get("score", 0) or 0) >= MIN_API_SCORE
    ]
    if not candidates:
        result: dict[str, Any] = {"album": album, "artists": [], "score": 0}
        _write_cache(album, result)
        return result

    best = max(candidates, key=lambda item: int(item.get("score", 0) or 0))
    result = {
        "album": str(best.get("title", album)).strip() or album,
        "artists": _artist_credit_names(best),
        "score": int(best.get("score", 0) or 0),
        "mbid": str(best.get("id", "")).strip() or None,
    }
    _write_cache(album, result)
    return result


def _clean_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        " ".join(str(item).split()).strip()
        for item in value[:MAX_ALBUMS_PER_REQUEST]
        if str(item).strip()
    ]


async def find_album_artist_conflict(
    payload: dict[str, Any] | None,
) -> tuple[str, str] | None:
    """Return the conflicting album and artist when ownership is strongly verified."""
    if not isinstance(payload, dict):
        return None
    albums = _clean_names(payload.get("allowed_albums"))
    excluded_artists = _clean_names(payload.get("excluded_artists"))
    if not albums or not excluded_artists:
        return None

    excluded_by_key = {
        normalize_identity(artist): artist
        for artist in excluded_artists
        if normalize_identity(artist)
    }
    if not excluded_by_key:
        return None

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(8.0),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        ) as client:
            for album in albums:
                relationship = await _lookup_album_artists(album, client)
                for actual_artist in relationship.get("artists", []):
                    key = normalize_identity(str(actual_artist))
                    if key in excluded_by_key:
                        return str(relationship.get("album", album)), excluded_by_key[key]
    except httpx.HTTPError:
        return None
    return None
