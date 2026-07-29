"""Best-effort MusicBrainz recording lookup for shadow metadata analysis."""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any

import httpx
from rapidfuzz import fuzz

MUSICBRAINZ_API_URL = "https://musicbrainz.org/ws/2/recording"
MUSICBRAINZ_VERSION = "0.7.0"
MUSICBRAINZ_REPOSITORY = "https://github.com/steventrux/PlaylistMuse"
MATCH_THRESHOLD = 72.0
MIN_REQUEST_INTERVAL_SECONDS = 1.05

_UNDESIRED_VERSION_TERMS = {
    "karaoke": 45.0,
    "tribute": 40.0,
    "cover": 35.0,
    "live": 35.0,
    "rehearsal": 30.0,
    "360 reality audio": 30.0,
    "demo": 28.0,
    "remix": 28.0,
    "surround mix": 22.0,
    "5.1 mix": 22.0,
    "instrumental": 18.0,
    "quadraphonic": 15.0,
    "radio edit": 8.0,
}

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


def _release_group(release: dict[str, Any]) -> dict[str, Any]:
    value = release.get("release-group")
    return value if isinstance(value, dict) else {}


def _release_group_ids(recording: dict[str, Any]) -> list[str]:
    identifiers: list[str] = []
    for release in recording.get("releases") or []:
        if not isinstance(release, dict):
            continue
        identifier = str(_release_group(release).get("id", "")).strip()
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


def _date_year(value: Any) -> int | None:
    match = re.match(r"^(\d{4})", str(value or "").strip())
    return int(match.group(1)) if match else None


def _release_date(release: dict[str, Any]) -> str | None:
    release_group = _release_group(release)
    for value in (release.get("date"), release_group.get("first-release-date")):
        text = str(value or "").strip()
        if text:
            return text
    return None


def _release_secondary_types(release: dict[str, Any]) -> list[str]:
    values = _release_group(release).get("secondary-types") or []
    return [str(value).strip() for value in values if str(value).strip()]


def _term_penalty(values: list[str]) -> float:
    text = " ".join(values).casefold()
    penalties = []
    for term, penalty in _UNDESIRED_VERSION_TERMS.items():
        pattern = rf"(?<!\w){re.escape(term)}(?!\w)"
        if re.search(pattern, text):
            penalties.append(penalty)
    return min(60.0, sum(penalties))


def _release_quality(release: dict[str, Any]) -> float:
    release_group = _release_group(release)
    status = str(release.get("status", "")).strip().casefold()
    primary_type = str(release_group.get("primary-type", "")).strip().casefold()
    secondary_types = {value.casefold() for value in _release_secondary_types(release)}

    score = 0.0
    if status == "official":
        score += 45.0
    elif status == "bootleg":
        score -= 45.0

    score += {
        "album": 25.0,
        "single": 22.0,
        "ep": 18.0,
        "broadcast": -20.0,
    }.get(primary_type, 0.0)

    if "live" in secondary_types:
        score -= 45.0
    if "remix" in secondary_types or "dj-mix" in secondary_types:
        score -= 30.0
    if "mixtape/street" in secondary_types:
        score -= 20.0
    if "compilation" in secondary_types:
        score -= 8.0
    if _release_date(release):
        score += 5.0

    score -= _term_penalty([str(release.get("title", "")), *secondary_types])
    return score


def _preferred_release(recording: dict[str, Any]) -> dict[str, Any]:
    releases = [
        release
        for release in (recording.get("releases") or [])
        if isinstance(release, dict)
    ]
    if not releases:
        return {}

    def rank(release: dict[str, Any]) -> tuple[float, int]:
        year = _date_year(_release_date(release))
        return _release_quality(release), -(year or 9999)

    return max(releases, key=rank)


def _duration_score(
    expected_ms: int | None,
    actual_ms: Any,
) -> tuple[float | None, int | None]:
    if expected_ms is None:
        return None, None
    try:
        actual = int(actual_ms)
    except (TypeError, ValueError):
        return None, None
    delta = abs(actual - expected_ms)
    score = max(0.0, 100.0 - (delta / 300.0))
    return round(score, 1), delta


def _candidate_payload(
    recording: dict[str, Any],
    input_title: str,
    input_artists: str,
    expected_duration_ms: int | None,
) -> dict[str, Any]:
    artist_text, artists = _artist_credit(recording)
    title = str(recording.get("title", "")).strip()
    try:
        search_score = float(recording.get("score", 0) or 0)
    except (TypeError, ValueError):
        search_score = 0.0

    title_score = float(fuzz.token_set_ratio(input_title, title))
    artist_score = float(fuzz.token_set_ratio(input_artists, artist_text))
    lexical_score = round(
        search_score * 0.20 + title_score * 0.45 + artist_score * 0.35,
        1,
    )

    preferred_release = _preferred_release(recording)
    release_group = _release_group(preferred_release)
    release_quality_raw = _release_quality(preferred_release) if preferred_release else 0.0
    release_quality_score = round(
        max(0.0, min(100.0, release_quality_raw + 20.0)),
        1,
    )
    duration_score, duration_delta_ms = _duration_score(
        expected_duration_ms,
        recording.get("length"),
    )
    version_penalty = _term_penalty(
        [
            str(recording.get("disambiguation", "")),
            str(preferred_release.get("title", "")),
            str(preferred_release.get("status", "")),
            *_release_secondary_types(preferred_release),
        ]
    )
    if str(preferred_release.get("status", "")).strip().casefold() == "bootleg":
        version_penalty = min(60.0, version_penalty + 35.0)

    if duration_score is None:
        confidence = lexical_score * 0.80 + release_quality_score * 0.20
    else:
        confidence = (
            lexical_score * 0.60
            + duration_score * 0.30
            + release_quality_score * 0.10
        )
    confidence = round(max(0.0, confidence - version_penalty), 1)

    first_release_date = recording.get("first-release-date") or None
    release_date = _release_date(preferred_release)
    effective_release_year = _date_year(first_release_date) or _date_year(release_date)

    return {
        "matched": bool(recording.get("id"))
        and lexical_score >= MATCH_THRESHOLD
        and confidence >= MATCH_THRESHOLD,
        "confidence": confidence,
        "lexical_score": lexical_score,
        "search_score": round(search_score, 1),
        "title_score": round(title_score, 1),
        "artist_score": round(artist_score, 1),
        "duration_score": duration_score,
        "duration_delta_ms": duration_delta_ms,
        "version_penalty": round(version_penalty, 1),
        "release_quality_score": release_quality_score,
        "effective_release_year": effective_release_year,
        "recording_mbid": str(recording.get("id", "")).strip() or None,
        "recording_title": title or None,
        "recording_disambiguation": str(recording.get("disambiguation", "")).strip() or None,
        "length_ms": recording.get("length"),
        "first_release_date": first_release_date,
        "artists": artists,
        "isrcs": _string_ids(recording.get("isrcs")),
        "tags": _tag_names(recording),
        "release_mbid": str(preferred_release.get("id", "")).strip() or None,
        "release_title": str(preferred_release.get("title", "")).strip() or None,
        "release_status": str(preferred_release.get("status", "")).strip() or None,
        "release_date": release_date,
        "release_group_primary_type": str(release_group.get("primary-type", "")).strip() or None,
        "release_group_secondary_types": _release_secondary_types(preferred_release),
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

    async def search_track(
        self,
        title: str,
        artists: str,
        *,
        duration_ms: int | None = None,
    ) -> dict[str, Any] | None:
        """Return the best MusicBrainz candidate and confidence diagnostics."""
        query = build_recording_query(title, artists)
        response = await _rate_limited_get(
            self._client,
            params={"query": query, "fmt": "json", "limit": 25},
        )
        response.raise_for_status()
        payload = response.json()
        recordings = payload.get("recordings") if isinstance(payload, dict) else None
        if not isinstance(recordings, list):
            return None

        candidates = [
            _candidate_payload(recording, title, artists, duration_ms)
            for recording in recordings
            if isinstance(recording, dict)
        ]
        if not candidates:
            return None

        exact_candidates = [
            item for item in candidates if float(item.get("lexical_score", 0.0)) >= 90.0
        ]
        pool = exact_candidates or candidates

        clean_candidates = [
            item for item in pool if float(item.get("version_penalty", 0.0)) <= 0.0
        ]
        if clean_candidates:
            pool = clean_candidates

        if duration_ms is not None:
            close_candidates = [
                item
                for item in pool
                if item.get("duration_delta_ms") is not None
                and int(item["duration_delta_ms"]) <= 45000
            ]
            if close_candidates:
                pool = close_candidates

        def rank(item: dict[str, Any]) -> tuple[float, float, float, int, float]:
            year = int(item.get("effective_release_year") or 9999)
            return (
                float(item.get("confidence", 0.0)),
                float(item.get("duration_score") or 0.0),
                float(item.get("release_quality_score", 0.0)),
                -year,
                float(item.get("lexical_score", 0.0)),
            )

        return max(pool, key=rank)
