"""Optional ReccoBeats evidence and catalogue-backed recommendation discovery."""

from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from backend.reccobeats_http import clear_reccobeats_http_state, request_json
from backend.text_normalization import normalize_identity
from backend.version import USER_AGENT

DEFAULT_TIMEOUT_SECONDS = 4.0
BATCH_TIMEOUT_SECONDS = 6.0
RECOMMENDATION_TIMEOUT_SECONDS = 5.0
CACHE_TTL_SECONDS = 6 * 60 * 60
RECOMMENDATION_CACHE_TTL_SECONDS = 30 * 60
MAX_CACHE_ENTRIES = 512
MAX_RECOMMENDATION_CACHE_ENTRIES = 128
MAX_CONCURRENT_REQUESTS = 5
MAX_RECOMMENDATION_SEEDS = 3
MAX_RECOMMENDATION_SIZE = 30
SEARCH_SIZE = 20
ARTIST_FALLBACK_PAGES = 3

LOGGER = logging.getLogger(__name__)
_CACHE: dict[tuple[str, str], tuple[float, ReccoBeatsAudioEvidence]] = {}
_RECOMMENDATION_CACHE: dict[
    tuple[tuple[tuple[str, str], ...], int],
    tuple[float, tuple[dict[str, str], ...]],
] = {}
_RECOMMENDATION_LOCK_GUARD = threading.Lock()
_RECOMMENDATION_LOCKS: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop,
    asyncio.Lock,
] = weakref.WeakKeyDictionary()


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


def _recommendation_lock() -> asyncio.Lock:
    """Serialize whole recommendation discoveries without charging queue time to their timeout."""
    loop = asyncio.get_running_loop()
    with _RECOMMENDATION_LOCK_GUARD:
        lock = _RECOMMENDATION_LOCKS.get(loop)
        if lock is None:
            lock = asyncio.Lock()
            _RECOMMENDATION_LOCKS[loop] = lock
        return lock


def _cache_key(artist: str, title: str) -> tuple[str, str]:
    return normalize_identity(artist), normalize_identity(title)


def _prune_cache(now: float) -> None:
    expired = [key for key, value in _CACHE.items() if value[0] <= now]
    for key in expired:
        _CACHE.pop(key, None)
    while len(_CACHE) >= MAX_CACHE_ENTRIES:
        _CACHE.pop(next(iter(_CACHE)))


def _prune_recommendation_cache(now: float) -> None:
    expired = [
        key for key, value in _RECOMMENDATION_CACHE.items() if value[0] <= now
    ]
    for key in expired:
        _RECOMMENDATION_CACHE.pop(key, None)
    while len(_RECOMMENDATION_CACHE) >= MAX_RECOMMENDATION_CACHE_ENTRIES:
        _RECOMMENDATION_CACHE.pop(next(iter(_RECOMMENDATION_CACHE)))


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
    return await request_json(client, path, params=params)


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


async def _resolve_track_candidate(
    client: httpx.AsyncClient,
    artist: str,
    title: str,
) -> dict[str, Any] | None:
    candidate = await _search_track(client, artist, title)
    if candidate is not None:
        return candidate
    return await _search_artist_catalog(client, artist, title)


def _recommendation_candidate(candidate: dict[str, Any]) -> dict[str, str] | None:
    title = _track_title(candidate)
    artists = _track_artists(candidate)
    if not title or not artists:
        return None
    result = {
        "artist": ", ".join(artists),
        "title": title,
        "source": "reccobeats",
    }
    reccobeats_id = str(candidate.get("id", "")).strip()
    if reccobeats_id:
        result["reccobeats_id"] = reccobeats_id
    return result


def _normalized_anchor_tracks(
    tracks: list[dict[str, Any]],
    *,
    max_anchors: int,
) -> list[tuple[str, str]]:
    anchors: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for track in tracks:
        artist = " ".join(
            str(track.get("artists") or track.get("artist") or "").split()
        ).strip()
        title = " ".join(str(track.get("title") or "").split()).strip()
        key = _cache_key(artist, title)
        if not all(key) or key in seen:
            continue
        seen.add(key)
        anchors.append((artist, title))
        if len(anchors) >= max_anchors:
            break
    return anchors


async def recommendation_candidates_from_tracks(
    tracks: list[dict[str, Any]],
    *,
    limit: int = 20,
    max_anchors: int = MAX_RECOMMENDATION_SEEDS,
    client: httpx.AsyncClient | None = None,
    now: Callable[[], float] = time.monotonic,
) -> list[dict[str, str]]:
    """Return fail-open ReccoBeats recommendations from already verified playlist tracks."""
    bounded_limit = max(1, min(MAX_RECOMMENDATION_SIZE, int(limit)))
    bounded_anchors = max(1, min(MAX_RECOMMENDATION_SEEDS, int(max_anchors)))
    anchors = _normalized_anchor_tracks(tracks, max_anchors=bounded_anchors)
    if not anchors:
        return []

    current_time = now()
    anchor_keys = tuple(_cache_key(artist, title) for artist, title in anchors)
    cache_key = (anchor_keys, bounded_limit)
    cached = _RECOMMENDATION_CACHE.get(cache_key)
    if cached and cached[0] > current_time:
        return [dict(candidate) for candidate in cached[1]]

    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(DEFAULT_TIMEOUT_SECONDS),
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )

    async def discover() -> list[dict[str, str]]:
        matched = await asyncio.gather(
            *(
                _resolve_track_candidate(active_client, artist, title)
                for artist, title in anchors
            ),
            return_exceptions=True,
        )
        seed_ids = list(
            dict.fromkeys(
                str(candidate.get("id", "")).strip()
                for candidate in matched
                if isinstance(candidate, dict) and candidate.get("id")
            )
        )
        if not seed_ids:
            return []

        payload = await _request_json(
            active_client,
            "/track/recommendation",
            params={"seeds": ",".join(seed_ids), "size": bounded_limit},
        )
        anchor_identity = set(anchor_keys)
        seen: set[tuple[str, str]] = set()
        recommendations: list[dict[str, str]] = []
        for raw_candidate in _content(payload):
            candidate = _recommendation_candidate(raw_candidate)
            if candidate is None:
                continue
            key = _cache_key(candidate["artist"], candidate["title"])
            if not all(key) or key in anchor_identity or key in seen:
                continue
            seen.add(key)
            recommendations.append(candidate)
            if len(recommendations) >= bounded_limit:
                break
        return recommendations

    try:
        lock = _recommendation_lock()
        async with lock:
            # Another queued discovery may have populated this exact result while we waited.
            current_time = now()
            cached = _RECOMMENDATION_CACHE.get(cache_key)
            if cached and cached[0] > current_time:
                return [dict(candidate) for candidate in cached[1]]

            recommendations = await asyncio.wait_for(
                discover(),
                timeout=RECOMMENDATION_TIMEOUT_SECONDS,
            )
            _prune_recommendation_cache(current_time)
            _RECOMMENDATION_CACHE[cache_key] = (
                now() + RECOMMENDATION_CACHE_TTL_SECONDS,
                tuple(dict(candidate) for candidate in recommendations),
            )
            return recommendations
    except (asyncio.TimeoutError, httpx.HTTPError, ValueError, TypeError) as error:
        LOGGER.info(
            "ReccoBeats recommendation discovery unavailable anchors=%s error=%s",
            len(anchors),
            type(error).__name__,
        )
        return []
    finally:
        if owns_client:
            await active_client.aclose()


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
    """Fetch optional evidence with a hard batch budget; unfinished work is neutral."""
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
        tasks = [asyncio.create_task(one(client, track)) for track in tracks]
        done, pending = await asyncio.wait(
            tasks,
            timeout=BATCH_TIMEOUT_SECONDS,
        )
        if pending:
            LOGGER.info(
                "ReccoBeats audio batch budget reached completed=%s total=%s timeout_seconds=%s",
                len(done),
                len(tasks),
                BATCH_TIMEOUT_SECONDS,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

        results: list[ReccoBeatsAudioEvidence] = []
        for task in tasks:
            if task.cancelled() or not task.done():
                results.append(ReccoBeatsAudioEvidence())
                continue
            try:
                result = task.result()
            except Exception:  # noqa: BLE001 - third-party enrichment is intentionally fail-open.
                result = ReccoBeatsAudioEvidence()
            results.append(
                result
                if isinstance(result, ReccoBeatsAudioEvidence)
                else ReccoBeatsAudioEvidence()
            )
        return results


def _clear_cache() -> None:
    """Clear the in-memory ReccoBeats caches for tests."""
    _CACHE.clear()
    _RECOMMENDATION_CACHE.clear()
    with _RECOMMENDATION_LOCK_GUARD:
        _RECOMMENDATION_LOCKS.clear()
    clear_reccobeats_http_state()
