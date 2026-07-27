"""Resolve AI suggestions against the YouTube Music catalogue."""

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


def _is_excluded(title: str, *, live: bool, covers: bool, remixes: bool) -> bool:
    normalized = title.casefold()
    if live and re.search(r"\b(live|concert|session)\b", normalized):
        return True
    if remixes and re.search(r"\b(remix|mix|edit|mashup)\b", normalized):
        return True
    if covers and re.search(r"\b(cover|tribute|karaoke)\b", normalized):
        return True
    return False


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

        title_score = fuzz.token_set_ratio(candidate["title"], title)
        artist_score = fuzz.token_set_ratio(candidate["artist"], artists)
        score = title_score * 0.65 + artist_score * 0.35
        if best is None or score > best[0]:
            best = (score, result)

    if best is None or best[0] < 65:
        return None

    result = best[1]
    thumbnails = result.get("thumbnails") or []
    thumbnail = thumbnails[-1].get("url") if thumbnails else None
    album = result.get("album") or {}
    return {
        "video_id": result["videoId"],
        "title": result.get("title"),
        "artists": _artist_text(result),
        "album": album.get("name"),
        "duration": result.get("duration"),
        "thumbnail_url": thumbnail,
        "url": f"https://music.youtube.com/watch?v={result['videoId']}",
        "match_score": round(best[0], 1),
    }


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
