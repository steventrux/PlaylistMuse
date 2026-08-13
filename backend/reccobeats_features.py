"""Optional ReccoBeats audio-feature evidence for creative-fit evaluation."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from backend.text_normalization import normalize_identity
from backend.version import USER_AGENT

API_ROOT = "https://api.reccobeats.com/v1"
DEFAULT_TIMEOUT_SECONDS = 4.0
CACHE_TTL_SECONDS = 6 * 60 * 60
MAX_CACHE_ENTRIES = 512
MAX_CONCURRENT_REQUESTS = 5
SEARCH_SIZE = 20
ARTIST_FALLBACK_PAGES = 3

LOGGER = logging.getLogger(__name__)
_CACHE: dict[tuple[str, str], tuple[float, ReccoBeatsAudioEvidence]] = {}


@dataclass(frozen=True, slots=True)
class ReccoBeatsAudioEvidence:
    """Soft quantitative evidence attached to one strictly matched catalogue track."""

    match_source: str = ""
    danceability: float | None = None
    energy: float | None = None
    valence: float | None = None
    tempo: float | None = None
    liveness: float | None = None
    acousticness: float | None = None
    instrumentalness: float | None = None
    speechiness: float | None = None
    loudness: float | None = None

    @property
    def available(self) -> bool:
        return bool(self.features)

    @property
    def features(self) -> dict[str, float]:
        values = {
            "danceability": self.danceability,
            "energy": self.energy,
            "valence": self.valence,
            "tempo": self.tempo,
            "liveness": self.liveness,
            "acousticness": self.acousticness,
            "instrumentalness": self.instrumentalness,
            "speechiness": self.speechiness,
            "loudness": self.loudness,
        }
        return {key: value for key, value in values.items() if value is not None}


def _cache_key(artist: str, title: str) -> tuple[str, str]:
    return normalize_identity(artist), normalize_identity(title)


def _prune_cache(now: float) -> None:
    expired = [key for key, value in _CACHE.items() if value[0] <= now]
    for key in expired:
        _CACHE.pop(key, None)
    while len(_CACHE) >= MAX_CACHE_ENTRIES:
        _CACHE.pop(next(iter(_CACHE)))


def _content(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    raw = payload.get("content", [])
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _track_title(candidate: dict[str, Any]) -> str:
    return str(
        candidate.get("trackTitle")
        or candidate.get("name")
        or candidate.get("title")
        or ""
    ).strip()


def _track_artists(candidate: dict[str, Any]) -> tuple[str, ...]:
    raw = candidate.get("artists", [])
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return ()
    names: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if name:
            names.append(name)
    return tuple(names)


def _strict_track_match(
    candidate: dict[str, Any],
    *,
    artist: str,
    title: str,
) -> bool:
    expected_title = normalize_identity(title)
    expected_artist = normalize_identity(artist)
    if not expected_title or not expected_artist:
        return False
    if normalize_identity(_track_title(candidate)) != expected_title:
        return False
    return expected_artist in {
        normalize_identity(value) for value in _track_artists(candidate)
    }


def _exact_artist(
    candidates: list[dict[str, Any]],
    artist: str,
) -> dict[str, Any] | None:
    expected = normalize_identity(artist)
    if not expected:
        return None
    return next(
        (
            item
            for item in candidates
            if normalize_identity(str(item.get("name", ""))) == expected
            and item.get("id")
        ),
        None,
    )


async def _request_json(
    client: httpx.AsyncClient,
    path: str,
    *,
    params: dict[str, Any] | None = None,
) -> Any:
    url = f"{API_ROOT}{path}"
    for attempt in range(2):
        response = await client.get(url, params=params)
        if response.status_code != 429 or attempt == 1:
            response.raise_for_status()
            return response.json()
        try:
            retry_after = float(response.headers.get("Retry-After", "0.5"))
        except ValueError:
            retry_after = 0.5
        await asyncio.sleep(min(2.0, max(0.25, retry_after)))
    return {}


async def _search_track(
    client: httpx.AsyncClient,
    artist: str,
    title: str,
) -> dict[str, Any] | None:
    queries = (title, f"{artist} {title}")
    seen_queries: set[str] = set()
    for query in queries:
        normalized_query = normalize_identity(query)
        if not normalized_query or normalized_query in seen_queries:
            continue
        seen_queries.add(normalized_query)
        payload = await _request_json(
            client,
            "/track/search",
            params={"searchText": query, "size": SEARCH_SIZE, "page": 0},
        )
        for candidate in _content(payload):
            if _strict_track_match(candidate, artist=artist, title=title):
                return candidate
    return None


async def _search_artist_catalog(
    client: httpx.AsyncClient,
    artist: str,
    title: str,
) -> dict[str, Any] | None:
    artist_payload = await _request_json(
        client,
        "/artist/search",
        params={"searchText": artist, "size": SEARCH_SIZE, "page": 0},
    )
    matched_artist = _exact_artist(_content(artist_payload), artist)
    if matched_artist is None:
        return None

    artist_id = str(matched_artist.get("id", "")).strip()
    if not artist_id:
        return None

    expected_title = normalize_identity(title)
    for page in range(ARTIST_FALLBACK_PAGES):
        payload = await _request_json(
            client,
            f"/artist/{artist_id}/track",
            params={"size": SEARCH_SIZE, "page": page},
        )
        tracks = _content(payload)
        for candidate in tracks:
            if normalize_identity(_track_title(candidate)) == expected_title:
                return candidate
        if len(tracks) < SEARCH_SIZE:
            break
    return None


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _unit_interval(value: Any) -> float | None:
    number = _finite_number(value)
    if number is None or number < 0.0 or number > 1.0:
        return None
    return number


def _positive_number(value: Any) -> float | None:
    number = _finite_number(value)
    if number is None or number <= 0.0:
        return None
    return number


def _evidence_from_payload(
    payload: Any,
    *,
    match_source: str,
) -> ReccoBeatsAudioEvidence:
    if not isinstance(payload, dict):
        return ReccoBeatsAudioEvidence()
    return ReccoBeatsAudioEvidence(
        match_source=match_source,
        danceability=_unit_interval(payload.get("danceability")),
        energy=_unit_interval(payload.get("energy")),
        valence=_unit_interval(payload.get("valence")),
        tempo=_positive_number(payload.get("tempo")),
        liveness=_unit_interval(payload.get("liveness")),
        acousticness=_unit_interval(payload.get("acousticness")),
        instrumentalness=_unit_interval(payload.get("instrumentalness")),
        speechiness=_unit_interval(payload.get("speechiness")),
        loudness=_finite_number(payload.get("loudness")),
    )


async def audio_evidence_for_track(
    artist: str,
    title: str,
    *,
    client: httpx.AsyncClient | None = None,
    now: Callable[[], float] = time.monotonic,
) -> ReccoBeatsAudioEvidence:
    """Return audio features only for a conservatively matched ReccoBeats track."""
    normalized_artist = " ".join(str(artist).split()).strip()
    normalized_title = " ".join(str(title).split()).strip()
    if not normalized_artist or not normalized_title:
        return ReccoBeatsAudioEvidence()

    current_time = now()
    cache_key = _cache_key(normalized_artist, normalized_title)
    cached = _CACHE.get(cache_key)
    if cached and cached[0] > current_time:
        return cached[1]

    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(DEFAULT_TIMEOUT_SECONDS),
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        candidate = await _search_track(
            active_client,
            normalized_artist,
            normalized_title,
        )
        match_source = "track_search"
        if candidate is None:
            candidate = await _search_artist_catalog(
                active_client,
                normalized_artist,
                normalized_title,
            )
            match_source = "artist_catalog"

        if candidate is None or not candidate.get("id"):
            evidence = ReccoBeatsAudioEvidence()
            _prune_cache(current_time)
            _CACHE[cache_key] = (now() + CACHE_TTL_SECONDS, evidence)
            return evidence

        payload = await _request_json(
            active_client,
            f"/track/{candidate['id']}/audio-features",
        )
        evidence = _evidence_from_payload(payload, match_source=match_source)
        _prune_cache(current_time)
        _CACHE[cache_key] = (now() + CACHE_TTL_SECONDS, evidence)
        return evidence
    except (httpx.HTTPError, ValueError, TypeError) as error:
        LOGGER.info(
            "ReccoBeats audio evidence unavailable for %s — %s: %s",
            normalized_artist,
            normalized_title,
            type(error).__name__,
        )
        return ReccoBeatsAudioEvidence()
    finally:
        if owns_client:
            await active_client.aclose()


async def audio_evidence_for_tracks(
    tracks: list[dict[str, Any]],
) -> list[ReccoBeatsAudioEvidence]:
    """Fetch optional ReccoBeats evidence concurrently; all failures are neutral."""
    if not tracks:
        return []

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async def one(
        client: httpx.AsyncClient,
        track: dict[str, Any],
    ) -> ReccoBeatsAudioEvidence:
        artist = str(track.get("artist") or track.get("artists") or "").strip()
        title = str(track.get("title") or "").strip()
        async with semaphore:
            return await audio_evidence_for_track(
                artist,
                title,
                client=client,
            )

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(DEFAULT_TIMEOUT_SECONDS),
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    ) as client:
        results = await asyncio.gather(
            *(one(client, track) for track in tracks),
            return_exceptions=True,
        )

    return [
        result
        if isinstance(result, ReccoBeatsAudioEvidence)
        else ReccoBeatsAudioEvidence()
        for result in results
    ]


def _clear_cache() -> None:
    """Clear the in-memory evidence cache for tests."""
    _CACHE.clear()
