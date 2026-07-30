"""Non-blocking album and playlist artwork enrichment."""

from __future__ import annotations

import asyncio
import json
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import httpx
from rapidfuzz import fuzz

from backend.config import DATA_DIR

MUSICBRAINZ_RELEASE_GROUP_URL = "https://musicbrainz.org/ws/2/release-group"
COVER_ART_ARCHIVE_URL = "https://coverartarchive.org/release-group"
REQUEST_INTERVAL_SECONDS = 1.05
CACHE_MAX_AGE = timedelta(days=90)
CACHE_SCHEMA_VERSION = 1

_rate_limit_lock = asyncio.Lock()
_cache_lock = asyncio.Lock()
_last_request_started = 0.0


def artwork_cache_path() -> Path:
    configured = os.getenv("PLAYLISTMUSE_ARTWORK_CACHE_PATH", "").strip()
    return Path(configured) if configured else DATA_DIR / "artwork-cache.json"


def _user_agent() -> str:
    contact = os.getenv("PLAYLISTMUSE_MUSICBRAINZ_CONTACT", "").strip()
    identity = contact or "https://github.com/steventrux/PlaylistMuse"
    return f"PlaylistMuse/0.8.0 ({identity})"


def _normalize(value: Any) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or "").casefold())
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(part for part in re.split(r"[\W_]+", without_marks) if part)


def _quote(value: str) -> str:
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _artist_credit(release_group: Mapping[str, Any]) -> str:
    names: list[str] = []
    for credit in release_group.get("artist-credit") or []:
        if not isinstance(credit, Mapping):
            continue
        artist = credit.get("artist")
        if not isinstance(artist, Mapping):
            continue
        name = str(artist.get("name", "")).strip()
        if name:
            names.append(name)
    return ", ".join(names)


def _cache_key(album: str, artists: str) -> str:
    return f"{_normalize(artists)}::{_normalize(album)}"


def _read_cache(path: Path) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, Mapping) or payload.get("schema_version") != CACHE_SCHEMA_VERSION:
        return {}
    entries = payload.get("entries")
    return dict(entries) if isinstance(entries, Mapping) else {}


def _write_cache(path: Path, entries: Mapping[str, Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "entries": entries,
    }
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _cache_entry_is_fresh(entry: Mapping[str, Any]) -> bool:
    try:
        cached_at = datetime.fromisoformat(str(entry.get("cached_at", "")))
    except ValueError:
        return False
    if cached_at.tzinfo is None:
        cached_at = cached_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - cached_at <= CACHE_MAX_AGE


async def _musicbrainz_get(
    client: httpx.AsyncClient,
    params: dict[str, Any],
) -> httpx.Response:
    global _last_request_started

    async with _rate_limit_lock:
        loop = asyncio.get_running_loop()
        elapsed = loop.time() - _last_request_started
        delay = REQUEST_INTERVAL_SECONDS - elapsed
        if _last_request_started and delay > 0:
            await asyncio.sleep(delay)
        _last_request_started = loop.time()
        return await client.get(MUSICBRAINZ_RELEASE_GROUP_URL, params=params)


def _best_release_group(
    payload: Mapping[str, Any],
    album: str,
    artists: str,
) -> dict[str, Any] | None:
    candidates = payload.get("release-groups")
    if not isinstance(candidates, list):
        return None

    best: tuple[float, dict[str, Any]] | None = None
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        mbid = str(candidate.get("id", "")).strip()
        title = str(candidate.get("title", "")).strip()
        artist_text = _artist_credit(candidate)
        if not mbid or not title or not artist_text:
            continue

        title_score = float(fuzz.token_set_ratio(album, title))
        artist_score = float(fuzz.token_set_ratio(artists, artist_text))
        try:
            search_score = float(candidate.get("score", 0) or 0)
        except (TypeError, ValueError):
            search_score = 0.0

        primary_type = str(candidate.get("primary-type", "")).strip().casefold()
        type_bonus = 4.0 if primary_type in {"album", "single", "ep"} else 0.0
        score = title_score * 0.50 + artist_score * 0.35 + search_score * 0.15 + type_bonus

        if title_score < 75.0 or artist_score < 70.0:
            continue
        normalized = {
            "release_group_mbid": mbid,
            "release_group_title": title,
            "release_group_artist": artist_text,
            "first_release_date": candidate.get("first-release-date") or None,
            "primary_type": candidate.get("primary-type") or None,
            "match_score": round(score, 1),
        }
        if best is None or score > best[0]:
            best = (score, normalized)

    if best is None or best[0] < 80.0:
        return None
    return best[1]


async def _cover_art_url(
    client: httpx.AsyncClient,
    release_group_mbid: str,
) -> str | None:
    response = await client.get(
        f"{COVER_ART_ARCHIVE_URL}/{release_group_mbid}",
        headers={"Accept": "application/json"},
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    payload = response.json()
    images = payload.get("images") if isinstance(payload, Mapping) else None
    if not isinstance(images, list):
        return None

    front = next(
        (
            image
            for image in images
            if isinstance(image, Mapping) and image.get("front") is True
        ),
        None,
    )
    selected = front or next(
        (image for image in images if isinstance(image, Mapping)),
        None,
    )
    if not isinstance(selected, Mapping):
        return None
    thumbnails = selected.get("thumbnails")
    if isinstance(thumbnails, Mapping):
        for size in ("500", "1200", "250"):
            value = str(thumbnails.get(size, "")).strip()
            if value:
                return value.replace("http://", "https://", 1)
    image = str(selected.get("image", "")).strip()
    return image.replace("http://", "https://", 1) if image else None


async def _lookup_album_artwork(
    client: httpx.AsyncClient,
    album: str,
    artists: str,
) -> dict[str, Any]:
    query = f"releasegroup:{_quote(album)} AND artistname:{_quote(artists)}"
    response = await _musicbrainz_get(
        client,
        {"query": query, "fmt": "json", "limit": 10},
    )
    response.raise_for_status()
    match = _best_release_group(response.json(), album, artists)
    if match is None:
        return {"found": False}

    cover_url = await _cover_art_url(client, match["release_group_mbid"])
    if not cover_url:
        return {"found": False}
    return {
        "found": True,
        **match,
        "album_cover_url": cover_url,
    }


def _fallback_track(track: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "video_id": track.get("video_id"),
        "title": str(track.get("title", "")),
        "artists": str(track.get("artists", "")),
        "album": track.get("album"),
        "album_cover_url": track.get("thumbnail_url"),
        "release_group_mbid": None,
        "release_group_title": None,
        "artwork_source": "youtube",
    }


def _playlist_cover_urls(
    enriched: list[dict[str, Any]],
    tracks: list[Mapping[str, Any]],
) -> list[str]:
    urls: list[str] = []
    for item in enriched:
        if item.get("artwork_source") != "cover_art_archive":
            continue
        url = str(item.get("album_cover_url", "")).strip()
        if url and url not in urls:
            urls.append(url)
        if len(urls) == 4:
            return urls

    for track in tracks:
        url = str(track.get("thumbnail_url", "")).strip()
        if url and url not in urls:
            urls.append(url)
        if len(urls) == 4:
            break

    if not urls:
        return []
    while len(urls) < 4:
        urls.append(urls[len(urls) % len(urls)])
    return urls[:4]


async def resolve_playlist_artwork(
    tracks: list[Mapping[str, Any]],
    *,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    """Enrich tracks with release-group artwork without affecting playlist creation."""
    path = cache_path or artwork_cache_path()
    async with _cache_lock:
        cache = await asyncio.to_thread(_read_cache, path)

    headers = {
        "User-Agent": _user_agent(),
        "Accept": "application/json",
    }
    timeout = httpx.Timeout(7.0)
    resolved_by_key: dict[str, dict[str, Any]] = {}
    cache_changed = False

    async with httpx.AsyncClient(
        headers=headers,
        timeout=timeout,
        follow_redirects=True,
    ) as client:
        for track in tracks:
            album = str(track.get("album", "") or "").strip()
            artists = str(track.get("artists", "") or "").strip()
            if not album or not artists:
                continue
            key = _cache_key(album, artists)
            if key in resolved_by_key:
                continue

            cached = cache.get(key)
            if isinstance(cached, Mapping) and _cache_entry_is_fresh(cached):
                resolved_by_key[key] = dict(cached)
                continue

            try:
                lookup = await _lookup_album_artwork(client, album, artists)
            except (httpx.HTTPError, ValueError, json.JSONDecodeError):
                continue

            entry = {
                **lookup,
                "cached_at": datetime.now(timezone.utc).isoformat(),
            }
            cache[key] = entry
            resolved_by_key[key] = entry
            cache_changed = True

    if cache_changed:
        async with _cache_lock:
            await asyncio.to_thread(_write_cache, path, cache)

    enriched: list[dict[str, Any]] = []
    for track in tracks:
        fallback = _fallback_track(track)
        album = str(track.get("album", "") or "").strip()
        artists = str(track.get("artists", "") or "").strip()
        if not album or not artists:
            enriched.append(fallback)
            continue

        entry = resolved_by_key.get(_cache_key(album, artists))
        if not isinstance(entry, Mapping) or not entry.get("found"):
            enriched.append(fallback)
            continue

        enriched.append(
            {
                **fallback,
                "album_cover_url": entry.get("album_cover_url") or fallback["album_cover_url"],
                "release_group_mbid": entry.get("release_group_mbid"),
                "release_group_title": entry.get("release_group_title"),
                "artwork_source": "cover_art_archive",
            }
        )

    return {
        "tracks": enriched,
        "playlist_cover_urls": _playlist_cover_urls(enriched, tracks),
    }
