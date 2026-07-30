"""Non-blocking album artwork lookup through MusicBrainz release groups."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import httpx
from rapidfuzz import fuzz

from backend.config import DATA_DIR

LOGGER = logging.getLogger(__name__)

MUSICBRAINZ_RELEASE_GROUP_URL = "https://musicbrainz.org/ws/2/release-group/"
COVER_ART_ARCHIVE_URL = "https://coverartarchive.org/release-group"
MIN_REQUEST_INTERVAL_SECONDS = 1.05
POSITIVE_CACHE_TTL = timedelta(days=180)
NEGATIVE_CACHE_TTL = timedelta(days=7)
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MIN_MATCH_SCORE = 80.0

ARTWORK_DIR = DATA_DIR / "artwork"
ARTWORK_IMAGE_DIR = ARTWORK_DIR / "images"
ARTWORK_CACHE_PATH = ARTWORK_DIR / "release-groups.json"
ARTWORK_IMAGE_DIR.mkdir(parents=True, exist_ok=True)

_cache_lock = asyncio.Lock()
_musicbrainz_lock = asyncio.Lock()
_last_musicbrainz_request = 0.0


def _normalize(value: Any) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or "").casefold())
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(part for part in re.split(r"[\W_]+", without_marks) if part)


def _cache_key(artists: str, album: str) -> str:
    identity = f"{_normalize(artists)}::{_normalize(album)}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _lucene_quote(value: str) -> str:
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _user_agent() -> str:
    contact = os.getenv("PLAYLISTMUSE_MUSICBRAINZ_CONTACT", "").strip()
    identity = contact or "https://github.com/steventrux/PlaylistMuse"
    return f"PlaylistMuse/0.7.0 ({identity})"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _read_cache_sync() -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(ARTWORK_CACHE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_cache_sync(payload: dict[str, dict[str, Any]]) -> None:
    ARTWORK_DIR.mkdir(parents=True, exist_ok=True)
    temporary = ARTWORK_CACHE_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.replace(ARTWORK_CACHE_PATH)
    try:
        ARTWORK_CACHE_PATH.chmod(0o600)
    except OSError:
        pass


async def _cached_entry(key: str) -> dict[str, Any] | None:
    async with _cache_lock:
        cache = await asyncio.to_thread(_read_cache_sync)
        entry = cache.get(key)
        return dict(entry) if isinstance(entry, dict) else None


async def _store_entry(key: str, entry: dict[str, Any]) -> None:
    async with _cache_lock:
        cache = await asyncio.to_thread(_read_cache_sync)
        cache[key] = entry
        await asyncio.to_thread(_write_cache_sync, cache)


def _entry_is_fresh(entry: Mapping[str, Any]) -> bool:
    try:
        stored_at = datetime.fromisoformat(str(entry.get("cached_at", "")))
    except ValueError:
        return False
    if stored_at.tzinfo is None:
        stored_at = stored_at.replace(tzinfo=timezone.utc)
    ttl = POSITIVE_CACHE_TTL if entry.get("status") == "found" else NEGATIVE_CACHE_TTL
    return _utc_now() - stored_at <= ttl


def _fallback(thumbnail_url: str | None) -> dict[str, Any]:
    return {
        "source": "youtube",
        "artwork_url": thumbnail_url,
        "release_group_mbid": None,
        "release_group_title": None,
    }


def _artist_credit_text(candidate: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for credit in candidate.get("artist-credit") or []:
        if not isinstance(credit, Mapping):
            continue
        name = str(credit.get("name", "")).strip()
        artist = credit.get("artist")
        if not name and isinstance(artist, Mapping):
            name = str(artist.get("name", "")).strip()
        if name:
            parts.append(name)
        join_phrase = str(credit.get("joinphrase", ""))
        if join_phrase:
            parts.append(join_phrase)
    return "".join(parts).strip()


def _candidate_score(candidate: Mapping[str, Any], album: str, artists: str) -> float:
    title = str(candidate.get("title", "")).strip()
    credited_artists = _artist_credit_text(candidate)
    try:
        search_score = float(candidate.get("score", 0) or 0)
    except (TypeError, ValueError):
        search_score = 0.0

    title_score = float(fuzz.token_set_ratio(album, title))
    artist_score = float(fuzz.token_set_ratio(artists, credited_artists))
    score = search_score * 0.25 + title_score * 0.45 + artist_score * 0.30

    primary_type = str(candidate.get("primary-type", "")).casefold()
    secondary_types = {
        str(value).casefold() for value in (candidate.get("secondary-types") or [])
    }
    if primary_type in {"album", "single", "ep"}:
        score += 4.0
    if secondary_types.intersection({"live", "remix", "dj-mix"}):
        score -= 25.0
    elif "compilation" in secondary_types:
        score -= 10.0

    if title_score < 78.0 or artist_score < 78.0:
        return 0.0
    return round(max(0.0, min(100.0, score)), 1)


async def _musicbrainz_get(
    client: httpx.AsyncClient,
    *,
    params: dict[str, Any],
) -> httpx.Response:
    global _last_musicbrainz_request

    async with _musicbrainz_lock:
        loop = asyncio.get_running_loop()
        elapsed = loop.time() - _last_musicbrainz_request
        delay = MIN_REQUEST_INTERVAL_SECONDS - elapsed
        if _last_musicbrainz_request and delay > 0:
            await asyncio.sleep(delay)
        _last_musicbrainz_request = loop.time()
        return await client.get(MUSICBRAINZ_RELEASE_GROUP_URL, params=params)


async def _find_release_group(
    client: httpx.AsyncClient,
    album: str,
    artists: str,
) -> dict[str, Any] | None:
    query = (
        f"releasegroup:{_lucene_quote(album.strip())} AND "
        f"artistname:{_lucene_quote(artists.strip())}"
    )
    response = await _musicbrainz_get(
        client,
        params={"query": query, "fmt": "json", "limit": 10},
    )
    response.raise_for_status()
    payload = response.json()
    candidates = payload.get("release-groups") if isinstance(payload, Mapping) else None
    if not isinstance(candidates, list):
        return None

    ranked: list[tuple[float, dict[str, Any]]] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        score = _candidate_score(candidate, album, artists)
        if score >= MIN_MATCH_SCORE:
            ranked.append((score, dict(candidate)))
    return max(ranked, key=lambda item: item[0])[1] if ranked else None


def _preferred_cover_url(payload: Any) -> str | None:
    images = payload.get("images") if isinstance(payload, Mapping) else None
    if not isinstance(images, list):
        return None

    usable = [image for image in images if isinstance(image, Mapping)]
    selected = next(
        (image for image in usable if image.get("front") and image.get("approved", True)),
        None,
    )
    selected = selected or next(
        (image for image in usable if image.get("approved", True)),
        None,
    )
    selected = selected or (usable[0] if usable else None)
    if not selected:
        return None

    thumbnails = selected.get("thumbnails")
    if isinstance(thumbnails, Mapping):
        for key in ("500", "large", "250", "1200"):
            value = str(thumbnails.get(key, "")).strip()
            if value:
                return value.replace("http://", "https://", 1)
    image = str(selected.get("image", "")).strip()
    return image.replace("http://", "https://", 1) if image else None


async def _release_group_cover_url(
    client: httpx.AsyncClient,
    release_group_mbid: str,
) -> str | None:
    response = await client.get(f"{COVER_ART_ARCHIVE_URL}/{release_group_mbid}")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return _preferred_cover_url(response.json())


def _extension(content_type: str) -> str:
    normalized = content_type.split(";", 1)[0].strip().casefold()
    return {
        "image/png": ".png",
        "image/webp": ".webp",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
    }.get(normalized, ".jpg")


async def _download_cover(
    client: httpx.AsyncClient,
    release_group_mbid: str,
    source_url: str,
) -> str:
    response = await client.get(source_url)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if not content_type.casefold().startswith("image/"):
        raise ValueError("Cover Art Archive returned a non-image response.")
    content = response.content
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise ValueError("Cover Art Archive image is empty or too large.")

    digest = hashlib.sha256(release_group_mbid.encode("utf-8")).hexdigest()
    filename = f"{digest}{_extension(content_type)}"
    destination = ARTWORK_IMAGE_DIR / filename
    if not destination.exists():
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(destination)
    return filename


def artwork_image_path(filename: str) -> Path | None:
    if not re.fullmatch(r"[a-f0-9]{64}\.(?:jpg|png|webp)", filename):
        return None
    path = ARTWORK_IMAGE_DIR / filename
    return path if path.is_file() else None


async def resolve_track_artwork(
    *,
    title: str,
    artists: str,
    album: str | None,
    thumbnail_url: str | None,
) -> dict[str, Any]:
    """Return release-group artwork without affecting playlist generation."""
    del title  # The release group is matched deliberately from album + artist only.

    clean_album = str(album or "").strip()
    clean_artists = str(artists or "").strip()
    fallback = _fallback(thumbnail_url)
    if not clean_album or not clean_artists:
        return fallback

    key = _cache_key(clean_artists, clean_album)
    cached = await _cached_entry(key)
    if cached and _entry_is_fresh(cached):
        if cached.get("status") != "found":
            return fallback
        filename = str(cached.get("image_filename", ""))
        if artwork_image_path(filename):
            return {
                "source": "musicbrainz",
                "artwork_url": f"/api/artwork/images/{filename}",
                "release_group_mbid": cached.get("release_group_mbid"),
                "release_group_title": cached.get("release_group_title"),
            }

    headers = {
        "User-Agent": _user_agent(),
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(10.0),
            follow_redirects=True,
        ) as client:
            release_group = await _find_release_group(client, clean_album, clean_artists)
            if release_group is None:
                await _store_entry(
                    key,
                    {"status": "missing", "cached_at": _utc_now().isoformat()},
                )
                return fallback

            mbid = str(release_group.get("id", "")).strip()
            release_group_title = str(release_group.get("title", "")).strip() or None
            if not mbid:
                return fallback

            cover_url = await _release_group_cover_url(client, mbid)
            if not cover_url:
                await _store_entry(
                    key,
                    {
                        "status": "missing",
                        "release_group_mbid": mbid,
                        "release_group_title": release_group_title,
                        "cached_at": _utc_now().isoformat(),
                    },
                )
                return fallback

            filename = await _download_cover(client, mbid, cover_url)
            await _store_entry(
                key,
                {
                    "status": "found",
                    "release_group_mbid": mbid,
                    "release_group_title": release_group_title,
                    "image_filename": filename,
                    "cached_at": _utc_now().isoformat(),
                },
            )
            return {
                "source": "musicbrainz",
                "artwork_url": f"/api/artwork/images/{filename}",
                "release_group_mbid": mbid,
                "release_group_title": release_group_title,
            }
    except (httpx.HTTPError, OSError, ValueError, json.JSONDecodeError) as error:
        LOGGER.info(
            "Album artwork enrichment failed open for %s — %s: %s",
            clean_artists,
            clean_album,
            error,
        )
        return fallback
