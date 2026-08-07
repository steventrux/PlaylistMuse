"""Random Last.fm suggestions for seed discovery."""

from __future__ import annotations

import logging
import secrets
from collections.abc import Sequence
from typing import Any, TypeVar

import httpx

from backend.lastfm import API_ROOT, USER_AGENT, _environment_timeout
from backend.lastfm_settings import lastfm_api_key

LOGGER = logging.getLogger(__name__)
T = TypeVar("T")

RANDOM_SEED_TAGS = (
    "rock",
    "classic rock",
    "hard rock",
    "alternative",
    "alternative rock",
    "indie",
    "indie rock",
    "blues",
    "blues rock",
    "soul",
    "neo soul",
    "funk",
    "rnb",
    "jazz",
    "folk",
    "americana",
    "country",
    "singer songwriter",
    "punk",
    "post punk",
    "new wave",
    "grunge",
    "britpop",
    "psychedelic",
    "progressive rock",
    "art rock",
    "garage rock",
    "stoner rock",
    "shoegaze",
    "dream pop",
    "post rock",
    "metal",
    "heavy metal",
    "doom metal",
    "power metal",
    "death metal",
    "black metal",
    "hardcore",
    "metalcore",
    "electronic",
    "electronica",
    "ambient",
    "downtempo",
    "trip hop",
    "synthpop",
    "disco",
    "house",
    "techno",
    "trance",
    "drum and bass",
    "dance",
    "pop",
    "hip hop",
    "rap",
    "reggae",
    "ska",
    "latin",
    "afrobeat",
    "bossa nova",
    "samba",
    "flamenco",
    "world",
    "classical",
    "soundtrack",
    "instrumental",
    "experimental",
    "acoustic",
    "lofi",
    "chillout",
)
RANDOM_SEED_KINDS = ("track", "artist", "album")
_METHODS = {
    "track": "tag.gettoptracks",
    "artist": "tag.gettopartists",
    "album": "tag.gettopalbums",
}
_CONTAINERS = {
    "track": ("tracks", "track"),
    "artist": ("topartists", "artist"),
    "album": ("albums", "album"),
}


def _choice(values: Sequence[T]) -> T:
    return secrets.choice(values)


def _artist_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name", "")).strip()
    return str(value or "").strip()


def _items(payload: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    container_name, item_name = _CONTAINERS[kind]
    raw_items = payload.get(container_name, {}).get(item_name, [])
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    return [item for item in raw_items if isinstance(item, dict)]


def _candidate(kind: str, item: dict[str, Any], tag: str) -> dict[str, str] | None:
    if kind == "artist":
        artist = str(item.get("name", "")).strip()
        if not artist:
            return None
        return {
            "kind": "artist",
            "artist": artist,
            "query": artist,
            "tag": tag,
            "source": "lastfm",
        }

    artist = _artist_name(item.get("artist"))
    name = str(item.get("name", "")).strip()
    if not artist or not name:
        return None

    if kind == "album":
        return {
            "kind": "album",
            "artist": artist,
            "album": name,
            "query": f"{artist} — {name}",
            "tag": tag,
            "source": "lastfm",
        }

    return {
        "kind": "track",
        "artist": artist,
        "title": name,
        "query": f"{artist} — {name}",
        "tag": tag,
        "source": "lastfm",
    }


def _parse_candidates(payload: dict[str, Any], kind: str, tag: str) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in _items(payload, kind):
        candidate = _candidate(kind, item, tag)
        if not candidate:
            continue
        identity = candidate["query"].casefold()
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append(candidate)
    return candidates


async def random_seed_suggestion(
    *,
    api_key: str | None = None,
    client: httpx.AsyncClient | None = None,
    attempts: int = 4,
) -> dict[str, str] | None:
    """Return a random real track, artist or album from Last.fm tag charts."""
    key = (api_key if api_key is not None else lastfm_api_key()).strip()
    if not key:
        return None

    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(_environment_timeout()),
        headers={"User-Agent": USER_AGENT},
    )
    try:
        for _ in range(max(1, min(8, attempts))):
            kind = _choice(RANDOM_SEED_KINDS)
            tag = _choice(RANDOM_SEED_TAGS)
            page = _choice((1, 2, 3, 4))
            try:
                response = await active_client.get(
                    API_ROOT,
                    params={
                        "method": _METHODS[kind],
                        "tag": tag,
                        "api_key": key,
                        "format": "json",
                        "limit": "50",
                        "page": str(page),
                    },
                )
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError, TypeError) as error:
                LOGGER.info("Last.fm random seed suggestion unavailable: %s", error)
                continue

            if not isinstance(payload, dict) or payload.get("error"):
                continue
            candidates = _parse_candidates(payload, kind, tag)
            if candidates:
                return _choice(candidates)
        return None
    finally:
        if owns_client:
            await active_client.aclose()
