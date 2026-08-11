"""Cross-entity validation for interpreted playlist constraints."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx

from backend.musicbrainz_client import rate_limited_get
from backend.text_normalization import normalize_identity
from backend.version import USER_AGENT

API_ROOT = "https://musicbrainz.org/ws/2"
CACHE_TTL_SECONDS = 180 * 24 * 60 * 60
NEGATIVE_CACHE_TTL_SECONDS = 24 * 60 * 60
MIN_API_SCORE = 90
MAX_NAMES_PER_REQUEST = 8


def _cache_path() -> Path:
    root = Path(os.getenv("PLAYLISTMUSE_DATA_DIR", "data"))
    return root / "constraint_relationship_cache.sqlite3"


def _pair_key(album: str, artist: str) -> str:
    return f"{normalize_identity(album)}|{normalize_identity(artist)}"


def _connect() -> sqlite3.Connection:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS album_artist_pair_cache (
            pair_key TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            expires_at REAL NOT NULL
        )
        """
    )
    return connection


def _read_cache(album: str, artist: str) -> dict[str, Any] | None:
    key = _pair_key(album, artist)
    if key == "|":
        return None
    try:
        with _connect() as connection:
            row = connection.execute(
                "SELECT payload, expires_at FROM album_artist_pair_cache WHERE pair_key = ?",
                (key,),
            ).fetchone()
            if not row:
                return None
            if float(row["expires_at"]) <= time.time():
                connection.execute(
                    "DELETE FROM album_artist_pair_cache WHERE pair_key = ?",
                    (key,),
                )
                return None
            payload = json.loads(str(row["payload"]))
            return payload if isinstance(payload, dict) else None
    except (sqlite3.Error, ValueError, TypeError, json.JSONDecodeError):
        return None


def _write_cache(album: str, artist: str, payload: dict[str, Any]) -> None:
    key = _pair_key(album, artist)
    if key == "|":
        return
    ttl = CACHE_TTL_SECONDS if payload.get("matches") else NEGATIVE_CACHE_TTL_SECONDS
    try:
        with _connect() as connection:
            connection.execute(
                """
                INSERT INTO album_artist_pair_cache(pair_key, payload, expires_at)
                VALUES (?, ?, ?)
                ON CONFLICT(pair_key) DO UPDATE SET
                    payload = excluded.payload,
                    expires_at = excluded.expires_at
                """,
                (key, json.dumps(payload, ensure_ascii=False), time.time() + ttl),
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
        name = (
            str(artist.get("name", "")).strip()
            if isinstance(artist, dict)
            else ""
        )
        name = name or str(credit.get("name", "")).strip()
        if name and name not in names:
            names.append(name)
    return names


async def _verify_album_artist_pair(
    album: str,
    artist: str,
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    cached = _read_cache(album, artist)
    if cached is not None:
        return cached

    response = await rate_limited_get(
        client,
        f"{API_ROOT}/release-group",
        params={
            "query": f'releasegroup:"{album}" AND artist:"{artist}"',
            "fmt": "json",
            "limit": "8",
        },
    )
    response.raise_for_status()

    expected_album = normalize_identity(album)
    expected_artist = normalize_identity(artist)
    matches: list[dict[str, Any]] = []
    for item in response.json().get("release-groups", []):
        if not isinstance(item, dict):
            continue
        if int(item.get("score", 0) or 0) < MIN_API_SCORE:
            continue
        if normalize_identity(str(item.get("title", ""))) != expected_album:
            continue
        credited = _artist_credit_names(item)
        if not any(
            normalize_identity(name) == expected_artist
            for name in credited
        ):
            continue
        matches.append(item)

    if not matches:
        result = {"album": album, "artist": artist, "matches": False}
        _write_cache(album, artist, result)
        return result

    best = max(matches, key=lambda item: int(item.get("score", 0) or 0))
    result = {
        "album": str(best.get("title", album)).strip() or album,
        "artist": artist,
        "matches": True,
        "score": int(best.get("score", 0) or 0),
        "mbid": str(best.get("id", "")).strip() or None,
    }
    _write_cache(album, artist, result)
    return result


def _clean_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        " ".join(str(item).split()).strip()
        for item in value[:MAX_NAMES_PER_REQUEST]
        if str(item).strip()
    ]


async def find_album_artist_conflict(
    payload: dict[str, Any] | None,
) -> tuple[str, str] | None:
    """Return a conflicting album/artist pair when MusicBrainz verifies it strongly."""
    if not isinstance(payload, dict):
        return None
    albums = _clean_names(payload.get("allowed_albums"))
    excluded_artists = _clean_names(payload.get("excluded_artists"))
    if not albums or not excluded_artists:
        return None

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(8.0),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        ) as client:
            for album in albums:
                for artist in excluded_artists:
                    relationship = await _verify_album_artist_pair(
                        album,
                        artist,
                        client,
                    )
                    if relationship.get("matches"):
                        return str(relationship.get("album", album)), artist
    except httpx.HTTPError:
        return None
    return None
