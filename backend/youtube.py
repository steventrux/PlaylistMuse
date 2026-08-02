"""Resolve AI suggestions and search seeds in the YouTube Music catalogue."""

from __future__ import annotations

import asyncio
import re
import unicodedata
from functools import lru_cache
from typing import Any

from rapidfuzz import fuzz
from ytmusicapi import YTMusic


_IDENTITY_SPLIT_RE = re.compile(r"[\W_]+")
_TITLE_TOKEN_RE = re.compile(r"[a-z0-9]+")
_LIVE_RE = re.compile(r"\b(live|concert|session)\b")
_REMIX_RE = re.compile(r"\b(remix|mix|edit|mashup)\b")
_COVER_RE = re.compile(r"\b(cover|tribute|karaoke)\b")
_COLLECTION_TERMS = (
    "medley",
    "full album",
    "greatest hits",
    "best of",
    "compilation",
    "complete album",
)
MIN_TITLE_SCORE = 70.0
MIN_ARTIST_SCORE = 75.0
MIN_COMBINED_SCORE = 72.0


@lru_cache(maxsize=1)
def _client() -> YTMusic:
    return YTMusic()


def _artist_text(result: dict[str, Any]) -> str:
    return ", ".join(str(item.get("name", "")) for item in result.get("artists", []))


def _album_name(result: dict[str, Any]) -> str:
    album = result.get("album") or {}
    if isinstance(album, dict):
        return str(album.get("name", "")).strip()
    return str(album).strip()


def _thumbnail(result: dict[str, Any]) -> str | None:
    thumbnails = result.get("thumbnails") or []
    return thumbnails[-1].get("url") if thumbnails else None


def _normalize_identity(value: str) -> str:
    """Normalize catalogue text so punctuation and accents do not create duplicates."""
    decomposed = unicodedata.normalize("NFKD", str(value).casefold())
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(part for part in _IDENTITY_SPLIT_RE.split(without_marks) if part)


def track_identity_key(title: str, artists: str) -> str:
    """Return a stable song identity independent from its YouTube video ID."""
    return f"{_normalize_identity(artists)}::{_normalize_identity(title)}"


def _serialize_song(result: dict[str, Any]) -> dict[str, Any] | None:
    video_id = result.get("videoId")
    title = str(result.get("title", "")).strip()
    artists = _artist_text(result)
    if not video_id or not title or not artists:
        return None
    return {
        "video_id": video_id,
        "title": title,
        "artists": artists,
        "album": _album_name(result) or None,
        "duration": result.get("duration"),
        "thumbnail_url": _thumbnail(result),
        "url": f"https://music.youtube.com/watch?v={video_id}",
    }


def _is_excluded(
    title: str,
    *,
    album: str = "",
    artists: str = "",
    live: bool,
    covers: bool,
    remixes: bool,
) -> bool:
    """Reject unwanted versions using all catalogue metadata, not only the title."""
    title_and_album = f"{title} {album}".casefold()
    normalized_artists = artists.casefold()
    if live and _LIVE_RE.search(title_and_album):
        return True
    if remixes and _REMIX_RE.search(title_and_album):
        return True
    if covers and (
        _COVER_RE.search(title_and_album) or _COVER_RE.search(normalized_artists)
    ):
        return True
    return False


def _looks_like_collection(candidate_title: str, result_title: str) -> bool:
    """Reject collection-style uploads when a normal single track was requested."""
    candidate = candidate_title.casefold()
    result = result_title.casefold()
    return any(term in result and term not in candidate for term in _COLLECTION_TERMS)


def _title_score(candidate_title: str, result_title: str) -> float:
    """Reward close titles and penalize noisy YouTube-style suffixes."""
    candidate_tokens = set(_TITLE_TOKEN_RE.findall(candidate_title.casefold()))
    result_tokens = set(_TITLE_TOKEN_RE.findall(result_title.casefold()))
    extra_tokens = max(0, len(result_tokens - candidate_tokens))
    penalty = min(28, extra_tokens * 2.5)
    return max(0.0, fuzz.token_set_ratio(candidate_title, result_title) - penalty)


def _artist_score(candidate_artist: str, result_artists: str) -> float:
    """Match artist spelling while still accepting punctuation and collaborator variants."""
    candidate = _normalize_identity(candidate_artist)
    result = _normalize_identity(result_artists)
    if not candidate or not result:
        return 0.0
    token_score = fuzz.token_set_ratio(candidate, result)
    compact_score = fuzz.ratio(candidate.replace(" ", ""), result.replace(" ", ""))
    return max(token_score, compact_score)


def _search_songs(query: str, limit: int) -> list[dict[str, Any]]:
    results = _client().search(query, filter="songs", limit=limit)
    songs: list[dict[str, Any]] = []
    seen_video_ids: set[str] = set()
    seen_track_keys: set[str] = set()

    for result in results:
        song = _serialize_song(result)
        if not song:
            continue
        identity = track_identity_key(song["title"], song["artists"])
        if song["video_id"] in seen_video_ids or identity in seen_track_keys:
            continue
        seen_video_ids.add(song["video_id"])
        seen_track_keys.add(identity)
        songs.append(song)
    return songs


async def search_songs(query: str, limit: int = 8) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_search_songs, query, limit)


def _resolve_one(candidate: dict[str, str], exclusions: dict[str, bool]) -> dict[str, Any] | None:
    query = f"{candidate['artist']} {candidate['title']}"
    results = _client().search(query, filter="songs", limit=12)
    best: tuple[float, dict[str, Any]] | None = None
    exclude_live = exclusions.get("exclude_live", True)
    exclude_covers = exclusions.get("exclude_covers", True)
    exclude_remixes = exclusions.get("exclude_remixes", True)

    for result in results:
        video_id = result.get("videoId")
        title = str(result.get("title", ""))
        artists = _artist_text(result)
        album = _album_name(result)
        if not video_id or not title or not artists:
            continue
        if _is_excluded(
            title,
            album=album,
            artists=artists,
            live=exclude_live,
            covers=exclude_covers,
            remixes=exclude_remixes,
        ):
            continue
        if _looks_like_collection(candidate["title"], title):
            continue

        title_score = _title_score(candidate["title"], title)
        artist_score = _artist_score(candidate["artist"], artists)
        if title_score < MIN_TITLE_SCORE or artist_score < MIN_ARTIST_SCORE:
            continue

        score = title_score * 0.68 + artist_score * 0.32
        if best is None or score > best[0]:
            best = (score, result)

    if best is None or best[0] < MIN_COMBINED_SCORE:
        return None

    song = _serialize_song(best[1])
    if not song:
        return None
    song["match_score"] = round(best[0], 1)
    song["description"] = candidate.get("description", "")
    song["reason"] = candidate.get("reason", "")
    source = str(candidate.get("source", "")).strip()
    if source:
        song["source"] = source
    lastfm_strategy = str(candidate.get("lastfm_strategy", "")).strip()
    if lastfm_strategy:
        song["lastfm_strategy"] = lastfm_strategy
    return song


async def resolve_candidates(
    candidates: list[dict[str, str]], exclusions: dict[str, bool]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    resolved: list[dict[str, Any]] = []
    unresolved: list[dict[str, str]] = []
    seen_video_ids: set[str] = set()
    seen_candidate_keys: set[str] = set()
    seen_track_keys: set[str] = set()

    for candidate in candidates:
        candidate_key = track_identity_key(candidate["title"], candidate["artist"])
        if candidate_key in seen_candidate_keys:
            continue

        track = await asyncio.to_thread(_resolve_one, candidate, exclusions)
        if not track:
            unresolved.append(candidate)
            continue

        track_key = track_identity_key(track["title"], track["artists"])
        if track["video_id"] in seen_video_ids or track_key in seen_track_keys:
            continue

        seen_candidate_keys.add(candidate_key)
        seen_video_ids.add(track["video_id"])
        seen_track_keys.add(track_key)
        resolved.append(track)

    return resolved, unresolved
