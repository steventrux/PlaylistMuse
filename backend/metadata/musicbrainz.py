"""Best-effort MusicBrainz recording lookup for shadow metadata analysis."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from rapidfuzz import fuzz

MUSICBRAINZ_API_URL = "https://musicbrainz.org/ws/2/recording"
MUSICBRAINZ_VERSION = "0.7.0"
MUSICBRAINZ_REPOSITORY = "https://github.com/steventrux/PlaylistMuse"
MATCH_THRESHOLD = 72.0
MIN_REQUEST_INTERVAL_SECONDS = 1.05

_rate_limit_lock = asyncio.Lock()
_last_request_started = 0.0


def _user_agent() -> str:
    contact = os.getenv("PLAYLISTMUSE_MUSICBRAINZ_CONTACT", "").strip()
    identity = contact or MUSICBRAINZ_REPOSITORY
    return f"PlaylistMuse/{MUSICBRAINZ_VERSION} ({identity})"


def _lucene_quote(value: str) -> str:
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def build_recording_query(title: str, artists: str) -> str:
    """Build a fielded MusicBrainz recording search query."""
    return (
        f"recording:{_lucene_quote(title.strip())} AND "
        f"artistname:{_lucene_quote(artists.strip())}"
    )


def _artist_credit(recording: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    names: list[str] = []
    artists: list[dict[str, str]] = []
    for credit in recording.get("artist-credit") or []:
        if not isinstance(credit, dict):
            continue
        artist = credit.get("artist")
        if not isinstance(artist, dict):
            continue
        name = str(artist.get("name", "")).strip()
        mbid = str(artist.get("id", "")).strip()
        if name:
            names.append(name)
        if name or mbid:
            artists.append({"name": name, "mbid": mbid})
    return ", ".join(names), artists


def _string_ids(values: Any) -> list[str]:
    identifiers: list[str] = []
    for value in values or []:
        if isinstance(value, dict):
            identifier = str(value.get("id", "")).strip()
        else:
            identifier = str(value).strip()
        if identifier and identifier not in identifiers:
            identifiers.append(identifier)
    return identifiers


def _release_group_ids(recording: dict[str, Any]) -> list[str]:
    identifiers: list[str] = []
    for release in recording.get("releases") or []:
        if not isinstance(release, dict):
            continue
        release_group = release.get("release-group")
        if not isinstance(release_group, dict):
            continue
        identifier = str(release_group.get("id", "")).strip()
        if identifier and identifier not in identifiers:
            identifiers.append(identifier)
    return identifiers[:20]


def _tag_names(recording: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    for item in recording.get("tags") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if name and name not in tags:
            tags.append(name)
    return tags[:20]


def _candidate_payload(
    recording: dict[str, Any],
    input_title: str,
    input_artists: str,
) -> dict[str, Any]:
    artist_text, artists = _artist_credit(recording)
    title = str(recording.get("title", "")).strip()
    try:
        search_score = float(recording.get("score", 0) or 0)
    except (TypeError, ValueError):
        search_score = 0.0

    title_score = float(fuzz.token_set_ratio(input_title, title))
    artist_score = float(fuzz.token_set_ratio(input_artists, artist_text))
    confidence = round(
        search_score * 0.20 + title_score * 0.45 + artist_score * 0.35,
        1,
    )

    releases = [
        release
        for release in (recording.get("releases") or [])
        if isinstance(release, dict)
    ]
    preferred_release = next(
        (release for release in releases if release.get("status") == "Official"),
        releases[0] if releases else {},
    )

    return {
        "matched": bool(recording.get("id")) and confidence >= MATCH_THRESHOLD,
        "confidence": confidence,
        "search_score": round(search_score, 1),
        "title_score": round(title_score, 1),
        "artist_score": round(artist_score, 1),
        "recording_mbid": str(recording.get("id", "")).strip() or None,
        "recording_title": title or None,
        "length_ms": recording.get("length"),
        "first_release_date": recording.get("first-release-date") or None,
        "artists": artists,
        "isrcs": _string_ids(recording.get("isrcs")),
        "tags": _tag_names(recording),
        "release_mbid": str(preferred_release.get("id", "")).strip() or None,
        "release_title": str(preferred_release.get("title", "")).strip() or None,
        "release_group_mbids": _release_group_ids(recording),
    }


async def _rate_limited_get(
    client: httpx.AsyncClient,
    *,
    params: dict[str, Any],
) -> httpx.Response:
    global _last_request_started

    async with _rate_limit_lock:
        loop = asyncio.get_running_loop()
        elapsed = loop.time() - _last_request_started
        delay = MIN_REQUEST_INTERVAL_SECONDS - elapsed
        if _last_request_started and delay > 0:
            await asyncio.sleep(delay)
        _last_request_started = loop.time()
        return await client.get(MUSICBRAINZ_API_URL, params=params)


class MusicBrainzClient:
    """Small async client that searches recordings without affecting playlist output."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 8.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            headers={
                "User-Agent": _user_agent(),
                "Accept": "application/json",
            },
            follow_redirects=True,
        )

    async def __aenter__(self) -> MusicBrainzClient:
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback
        if self._owns_client:
            await self._client.aclose()

    async def search_track(self, title: str, artists: str) -> dict[str, Any] | None:
        """Return the best MusicBrainz candidate and confidence diagnostics."""
        query = build_recording_query(title, artists)
        response = await _rate_limited_get(
            self._client,
            params={"query": query, "fmt": "json", "limit": 5},
        )
        response.raise_for_status()
        payload = response.json()
        recordings = payload.get("recordings") if isinstance(payload, dict) else None
        if not isinstance(recordings, list):
            return None

        candidates = [
            _candidate_payload(recording, title, artists)
            for recording in recordings
            if isinstance(recording, dict)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: float(item.get("confidence", 0.0)))
