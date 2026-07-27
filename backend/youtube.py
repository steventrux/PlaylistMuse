"""Resolve AI suggestions and search seeds in the YouTube Music catalogue."""

from __future__ import annotations

import asyncio
import re
from functools import lru_cache
from typing import Any

from rapidfuzz import fuzz
from ytmusicapi import YTMusic


@lru_cache(maxsize=1)
def _client() -> YTMusic:
    return YTMusic()


def _artist_text(result: dict[str, Any]) -> str:
    return ", ".join(str(item.get("name", "")) for item in result.get("artists", []))


def _thumbnail(result: dict[str, Any]) -> str | None:
    thumbnails = result.get("thumbnails") or []
    return thumbnails[-1].get("url") if thumbnails else None


def _serialize_song(result: dict[str, Any]) -> dict[str, Any] | None:
    video_id = result.get("videoId")
    title = str(result.get("title", "")).strip()
    artists = _artist_text(result)
    if not video_id or not title or not artists:
        return None
    album = result.get("album") or {}
    return {
        "video_id": video_id,
        "title": title,
        "artists": artists,
        "album": album.get("name"),
        "duration": result.get("duration"),
        "thumbnail_url": _thumbnail(result),
        "url": f"https://music.youtube.com/watch?v={video_id}",
    }


def _is_excluded(title: str, *, live: bool, covers: bool, remixes: bool) -> bool:
    normalized = title.casefold()
    if live and re.search(r"\b(live|concert|session)\b", normalized):
        return True
    if remixes and re.search(r"\b(remix|mix|edit|mashup)\b", normalized):
        return True
    if covers and re.search(r"\b(cover|tribute|karaoke)\b", normalized):
        return True
    return False


def _looks_like_collection(candidate_title: str, result_title: str) -> bool:
    """Reject collection-style uploads when a normal single track was requested."""
    candidate = candidate_title.casefold()
    result = result_title.casefold()
    collection_terms = (
        "medley",
        "full album",
        "greatest hits",
        "best of",
        "compilation",
        "complete album",
    )
    return any(term in result and term not in candidate for term in collection_terms)


def _title_score(candidate_title: str, result_title: str) -> float:
    """Reward close titles and penalize noisy YouTube-style suffixes."""
    candidate_tokens = set(re.findall(r"[a-z0-9]+", candidate_title.casefold()))
    result_tokens = set(re.findall(r"[a-z0-9]+", result_title.casefold()))
    extra_tokens = max(0, len(result_tokens - candidate_tokens))
    penalty = min(28, extra_tokens * 2.5)
    return max(0.0, fuzz.token_set_ratio(candidate_title, result_title) - penalty)


def _search_songs(query: str, limit: int) -> list[dict[str, Any]]:
    results = _client().search(query, filter="songs", limit=limit)
    songs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for result in results:
        song = _serialize_song(result)
        if not song or song["video_id"] in seen:
            continue
        seen.add(song["video_id"])
        songs.append(song)
    return songs


async def search_songs(query: str, limit: int = 8) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_search_songs, query, limit)


def _resolve_one(candidate: dict[str, str], exclusions: dict[str, bool]) -> dict[str, Any] | None:
    query = f"{candidate['artist']} {candidate['title']}"
    results = _client().search(query, filter="songs", limit=8)
    best: tuple[float, dict[str, Any]] | None = None

    for result in results:
        video_id = result.get("videoId")
        title = str(result.get("title", ""))
        artists = _artist_text(result)
        if not video_id or not title or not artists:
            continue
        if _is_excluded(
            title,
            live=exclusions.get("exclude_live", True),
            covers=exclusions.get("exclude_covers", True),
            remixes=exclusions.get("exclude_remixes", True),
        ):
            continue
        if _looks_like_collection(candidate["title"], title):
            continue

        title_score = _title_score(candidate["title"], title)
        artist_score = fuzz.token_set_ratio(candidate["artist"], artists)
        score = title_score * 0.68 + artist_score * 0.32
        if best is None or score > best[0]:
            best = (score, result)

    if best is None or best[0] < 65:
        return None

    song = _serialize_song(best[1])
    if not song:
        return None
    song["match_score"] = round(best[0], 1)
    return song


async def resolve_candidates(
    candidates: list[dict[str, str]], exclusions: dict[str, bool]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    resolved: list[dict[str, Any]] = []
    unresolved: list[dict[str, str]] = []

    for candidate in candidates:
        track = await asyncio.to_thread(_resolve_one, candidate, exclusions)
        if track:
            resolved.append(track)
        else:
            unresolved.append(candidate)
    return resolved, unresolved
