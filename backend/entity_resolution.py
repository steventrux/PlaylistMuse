"""Conservative MusicBrainz entity canonicalization for interpreted artist names."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx

from backend.musicbrainz_client import rate_limited_get
from backend.text_normalization import normalize_identity as _normalize
from backend.version import USER_AGENT

API_ROOT = "https://musicbrainz.org/ws/2"
CACHE_TTL_SECONDS = 180 * 24 * 60 * 60
MIN_API_SCORE = 90
MAX_NAMES_PER_REQUEST = 8
PURGE_INTERVAL_SECONDS = 3600

_last_purge_at = 0.0


def _cache_path() -> Path:
    root = Path(os.getenv("PLAYLISTMUSE_DATA_DIR", "data"))
    return root / "entity_resolution_cache.sqlite3"


def _connect() -> sqlite3.Connection:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS artist_entity_cache (
            normalized_name TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            expires_at REAL NOT NULL
        )
        """
    )
    return connection


def _read_cache(name: str) -> dict[str, str] | None:
    try:
        with _connect() as connection:
            row = connection.execute(
                "SELECT payload, expires_at FROM artist_entity_cache WHERE normalized_name = ?",
                (_normalize(name),),
            ).fetchone()
            if not row or float(row["expires_at"]) <= time.time():
                return None
            payload = json.loads(str(row["payload"]))
            return payload if isinstance(payload, dict) else None
    except (sqlite3.Error, ValueError, TypeError, json.JSONDecodeError):
        return None


def _write_cache(name: str, payload: dict[str, str]) -> None:
    global _last_purge_at
    try:
        with _connect() as connection:
            connection.execute(
                """
                INSERT INTO artist_entity_cache(normalized_name, payload, expires_at)
                VALUES (?, ?, ?)
                ON CONFLICT(normalized_name) DO UPDATE SET
                  payload = excluded.payload,
                  expires_at = excluded.expires_at
                """,
                (
                    _normalize(name),
                    json.dumps(payload, ensure_ascii=False),
                    time.time() + CACHE_TTL_SECONDS,
                ),
            )
            now = time.time()
            if now - _last_purge_at > PURGE_INTERVAL_SECONDS:
                connection.execute(
                    "DELETE FROM artist_entity_cache WHERE expires_at <= ?", (now,)
                )
                _last_purge_at = now
    except (sqlite3.Error, TypeError, ValueError):
        return


async def _search_artist(name: str, client: httpx.AsyncClient) -> dict[str, str] | None:
    cached = _read_cache(name)
    if cached is not None:
        return cached or None
    response = await rate_limited_get(
        client,
        f"{API_ROOT}/artist",
        params={
            "query": f'artist:"{name}"',
            "fmt": "json",
            "limit": "5",
        },
    )
    response.raise_for_status()
    candidates = [
        item
        for item in response.json().get("artists", [])
        if isinstance(item, dict)
    ]
    expected = _normalize(name)
    exact = [
        item
        for item in candidates
        if _normalize(str(item.get("name", ""))) == expected
    ]
    matches = exact or candidates
    if not matches:
        _write_cache(name, {})
        return None
    best = max(matches, key=lambda item: int(item.get("score", 0) or 0))
    score = int(best.get("score", 0) or 0)
    canonical = str(best.get("name", "")).strip()
    mbid = str(best.get("id", "")).strip()
    if score < MIN_API_SCORE or not canonical or not mbid:
        _write_cache(name, {})
        return None
    result = {
        "input": name,
        "name": canonical,
        "mbid": mbid,
        "score": str(score),
    }
    _write_cache(name, result)
    return result


async def canonicalize_interpretation(
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Canonicalize high-confidence artist fields without changing uncertain names."""
    if not isinstance(payload, dict):
        return payload
    fields = ("allowed_artists", "excluded_artists")
    names: list[str] = []
    for field_name in fields:
        raw = payload.get(field_name)
        if isinstance(raw, list):
            names.extend(str(value).strip() for value in raw if str(value).strip())
    unique = list(dict.fromkeys(names))[:MAX_NAMES_PER_REQUEST]
    if not unique:
        return payload

    resolved: dict[str, dict[str, str]] = {}
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(7.0),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        ) as client:
            for name in unique:
                entity = await _search_artist(name, client)
                if entity is not None:
                    resolved[_normalize(name)] = entity
    except httpx.HTTPError:
        return payload

    enriched = dict(payload)
    for field_name in fields:
        raw = payload.get(field_name)
        if not isinstance(raw, list):
            continue
        enriched[field_name] = [
            resolved.get(_normalize(str(value)), {}).get("name", str(value))
            for value in raw
        ]
    enriched["canonical_artist_entities"] = list(resolved.values())
    return enriched
