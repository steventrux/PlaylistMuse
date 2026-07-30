"""Fast, non-blocking playlist artwork lookup through MusicBrainz release groups."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

import httpx
from rapidfuzz import fuzz

from backend.config import DATA_DIR

LOGGER = logging.getLogger(__name__)

MUSICBRAINZ_RELEASE_GROUP_URL = "https://musicbrainz.org/ws/2/release-group/"
COVER_ART_ARCHIVE_RELEASE_GROUP_URL = "https://coverartarchive.org/release-group"
MIN_REQUEST_INTERVAL_SECONDS = 1.05
POSITIVE_CACHE_TTL = timedelta(days=180)
NEGATIVE_CACHE_TTL = timedelta(days=7)
MIN_MATCH_SCORE = 80.0

ARTWORK_DIR = DATA_DIR / "artwork"
ARTWORK_CACHE_PATH = ARTWORK_DIR / "release-groups.json"

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


def _identity(artists: str, album: str) -> tuple[str, str]:
    return _normalize(artists), _normalize(album)


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


async def _read_cache() -> dict[str, dict[str, Any]]:
    async with _cache_lock:
        return await asyncio.to_thread(_read_cache_sync)


async def _store_entries(entries: Mapping[str, dict[str, Any]]) -> None:
    if not entries:
        return
    async with _cache_lock:
        cache = await asyncio.to_thread(_read_cache_sync)
        cache.update(entries)
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


def _cover_art_url(release_group_mbid: str) -> str:
    return f"{COVER_ART_ARCHIVE_RELEASE_GROUP_URL}/{release_group_mbid}/front-500"


def _musicbrainz_result(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    mbid = str(entry.get("release_group_mbid", "")).strip()
    if entry.get("status") != "found" or not mbid:
        return None
    return {
        "source": "musicbrainz",
        "artwork_url": _cover_art_url(mbid),
        "release_group_mbid": mbid,
        "release_group_title": entry.get("release_group_title"),
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


def _release_group_query(items: Sequence[tuple[str, str]]) -> str:
    clauses = [
        "("
        f"releasegroup:{_lucene_quote(album)} AND "
        f"artistname:{_lucene_quote(artists)}"
        ")"
        for artists, album in items
    ]
    return " OR ".join(dict.fromkeys(clauses))


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


async def _search_release_groups(
    client: httpx.AsyncClient,
    items: Sequence[tuple[str, str]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Resolve up to four artist/album pairs with one MusicBrainz request."""
    unique_items = list(dict.fromkeys(items))
    if not unique_items:
        return {}

    response = await _musicbrainz_get(
        client,
        params={
            "query": _release_group_query(unique_items),
            "fmt": "json",
            "limit": 100,
        },
    )
    response.raise_for_status()
    payload = response.json()
    raw_candidates = payload.get("release-groups") if isinstance(payload, Mapping) else None
    candidates = [
        dict(candidate)
        for candidate in (raw_candidates or [])
        if isinstance(candidate, Mapping)
    ]

    matches: dict[tuple[str, str], dict[str, Any]] = {}
    for artists, album in unique_items:
        ranked = [
            (_candidate_score(candidate, album, artists), candidate)
            for candidate in candidates
        ]
        ranked = [item for item in ranked if item[0] >= MIN_MATCH_SCORE]
        if ranked:
            matches[_identity(artists, album)] = max(ranked, key=lambda item: item[0])[1]
    return matches


async def resolve_playlist_artwork(
    tracks: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return artwork for a playlist cover with at most one MusicBrainz request."""
    results = [_fallback(str(track.get("thumbnail_url") or "").strip() or None) for track in tracks]
    cache = await _read_cache()

    pending: dict[str, dict[str, Any]] = {}
    for index, track in enumerate(tracks):
        artists = str(track.get("artists") or "").strip()
        album = str(track.get("album") or "").strip()
        if not artists or not album:
            continue

        key = _cache_key(artists, album)
        entry = cache.get(key)
        if isinstance(entry, Mapping) and _entry_is_fresh(entry):
            cached_result = _musicbrainz_result(entry)
            if cached_result is not None:
                results[index] = cached_result
            continue

        item = pending.setdefault(
            key,
            {
                "artists": artists,
                "album": album,
                "indexes": [],
            },
        )
        item["indexes"].append(index)

    if not pending:
        return results

    headers = {
        "User-Agent": _user_agent(),
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(8.0),
            follow_redirects=True,
        ) as client:
            search_items = [
                (str(item["artists"]), str(item["album"]))
                for item in pending.values()
            ]
            matches = await _search_release_groups(client, search_items)
    except (httpx.HTTPError, ValueError, json.JSONDecodeError) as error:
        LOGGER.info("Playlist artwork enrichment failed open: %s", error)
        return results

    now = _utc_now().isoformat()
    cache_updates: dict[str, dict[str, Any]] = {}
    for key, item in pending.items():
        artists = str(item["artists"])
        album = str(item["album"])
        match = matches.get(_identity(artists, album))
        mbid = str((match or {}).get("id", "")).strip()
        if not match or not mbid:
            cache_updates[key] = {"status": "missing", "cached_at": now}
            continue

        entry = {
            "status": "found",
            "release_group_mbid": mbid,
            "release_group_title": str(match.get("title", "")).strip() or None,
            "cached_at": now,
        }
        cache_updates[key] = entry
        resolved = _musicbrainz_result(entry)
        if resolved is not None:
            for index in item["indexes"]:
                results[index] = resolved

    try:
        await _store_entries(cache_updates)
    except OSError as error:
        LOGGER.info("Playlist artwork cache could not be updated: %s", error)

    return results
