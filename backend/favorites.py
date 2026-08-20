"""Global list of favorite artists and tracks, used to bias future generations."""

from __future__ import annotations

import json
import re
import sqlite3
from contextvars import ContextVar
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.config import DATA_DIR
from backend.playlist_library import DATABASE_PATH, split_artist_credit
from backend.storage import read_json_object, write_secure_json

FAVORITES_PATH = DATA_DIR / "favorites.json"
MAX_FAVORITE_ARTISTS = 300
MAX_FAVORITE_TRACKS = 300
MAX_FAVORITE_NAME_LENGTH = 120

_FAVORITES_GENERIC_REQUEST_PATTERNS = (
    # A generic reference to the bookmarked collection, not scoped to artists or
    # tracks specifically -- treated as a request for both categories.
    re.compile(r"\bmy\s+favou?rites\b", re.IGNORECASE),  # English (US/UK spelling)
    re.compile(r"\b(?:i\s+miei|le\s+mie)\s+preferit[ei]\b", re.IGNORECASE),  # Italian
    re.compile(r"\bmes\s+favoris\b", re.IGNORECASE),  # French
    re.compile(r"\bmis\s+favoritos\b", re.IGNORECASE),  # Spanish
    re.compile(r"\bmeine\s+Favoriten\b", re.IGNORECASE),  # German
)
_FAVORITE_ARTISTS_REQUEST_PATTERNS = (
    re.compile(r"\bmy\s+favou?rite\s+artists\b", re.IGNORECASE),  # US/UK spelling
    re.compile(r"\bartisti\s+preferit[ei]\b", re.IGNORECASE),
    re.compile(r"\bmes\s+artistes\s+(?:favoris|préférés|préférées)\b", re.IGNORECASE),
    re.compile(r"\bmis\s+artistas\s+(?:favoritos|preferidos)\b", re.IGNORECASE),
    re.compile(r"\bmeine\s+Lieblingskünstler\b", re.IGNORECASE),
)
_FAVORITE_TRACKS_REQUEST_PATTERNS = (
    re.compile(r"\bmy\s+favou?rite\s+(?:songs|tracks)\b", re.IGNORECASE),  # US/UK spelling
    re.compile(r"\b(?:canzoni|brani|tracce)\s+preferit[ei]\b", re.IGNORECASE),
    re.compile(
        r"\bmes\s+(?:chansons|morceaux|titres)\s+(?:favoris|préférés|préférées)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bmis\s+(?:canciones|temas|pistas)\s+(?:favoritos|favoritas|preferidos|preferidas)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bmeine\s+Lieblings(?:songs|lieder|titel|tracks)\b", re.IGNORECASE),
)
# A favorites reference softened by an "inspired by"-style qualifier -- the listener
# wants the bookmarked collection to steer the generation more than the passive
# default bias below, but explicitly declined to request it as a hard, exclusive ask
# ("my favorite artists" alone). Matched independently of *where* in the prompt it
# appears (not just immediately before the favorites phrase): a prompt combining the
# two anywhere is read as one softened request, since demanding adjacency would miss
# the common "inspired by X, using my favorite artists" phrasing.
_INSPIRED_BY_QUALIFIER_PATTERNS = (
    re.compile(r"\binspired\s+by\b", re.IGNORECASE),  # English
    re.compile(r"\bispirat[oa]\s+(?:a|ai|alle?|da)\b", re.IGNORECASE),  # Italian
    re.compile(r"\binspir[ée]e?\s+(?:par|de)\b", re.IGNORECASE),  # French
    re.compile(r"\binspirad[oa]\s+(?:en|por)\b", re.IGNORECASE),  # Spanish
    re.compile(r"\binspiriert\s+von\b", re.IGNORECASE),  # German
)

_FAVORITE_ARTIST_ALLOWLIST: ContextVar[tuple[str, ...]] = ContextVar(
    "favorite_artist_allowlist", default=()
)


class FavoritesRequestLevel(str, Enum):
    """How strongly a prompt asks for bookmarked favorites, per category.

    EXPLICIT: a direct, unqualified ask ("my favorite artists") -- hard-restricts
    the artist pool and/or seeds bookmarked tracks verbatim (see backend.main).
    INSPIRED: the same phrase softened by an "inspired by"-style qualifier -- the
    generation prompt should weigh favorites noticeably more than the passive
    default, but must never hard-restrict the pool or override an explicit
    constraint, exclusion or quantity.
    NONE: no reference to the bookmarked collection at all -- favorites (if any
    are saved) are still folded in, but only as a mild, tie-breaking bias.
    """

    NONE = "none"
    INSPIRED = "inspired"
    EXPLICIT = "explicit"


def favorite_categories_requested_levels(
    prompt: str,
) -> tuple[FavoritesRequestLevel, FavoritesRequestLevel]:
    """Detect how strongly the prompt asks for bookmarked favorite artists/tracks.

    Returns (artists_level, tracks_level) so a prompt that names only one category
    ("i miei artisti preferiti") strengthens just that category, while a generic
    reference ("my favorites") covers both. Regex-based (no AI call): the actual
    restriction this feeds is a fast, local check, so the low false-positive/
    negative risk of pattern matching is an acceptable trade for avoiding extra
    generation latency. Deliberately narrow -- requires a clear reference to the
    saved favorites collection, not a generic singular use of the adjective ("my
    favorite song is...") which usually names one specific track, not the
    bookmarked list.
    """
    generic = any(pattern.search(prompt) for pattern in _FAVORITES_GENERIC_REQUEST_PATTERNS)
    artists_matched = generic or any(
        pattern.search(prompt) for pattern in _FAVORITE_ARTISTS_REQUEST_PATTERNS
    )
    tracks_matched = generic or any(
        pattern.search(prompt) for pattern in _FAVORITE_TRACKS_REQUEST_PATTERNS
    )
    inspired = any(pattern.search(prompt) for pattern in _INSPIRED_BY_QUALIFIER_PATTERNS)

    def _level(matched: bool) -> FavoritesRequestLevel:
        if not matched:
            return FavoritesRequestLevel.NONE
        return FavoritesRequestLevel.INSPIRED if inspired else FavoritesRequestLevel.EXPLICIT

    return _level(artists_matched), _level(tracks_matched)


def favorite_categories_explicitly_requested(prompt: str) -> tuple[bool, bool]:
    """Backward-compatible hard-request check -- True only at the EXPLICIT tier.

    Used to gate behavior that must stay reserved for an unqualified ask (the
    hard artist-pool restriction and the bookmarked-tracks-only shortcut in
    backend.main) -- an "inspired by my favorites" prompt should not trigger
    those, only the softer INSPIRED-tier guidance weighting.
    """
    artists_level, tracks_level = favorite_categories_requested_levels(prompt)
    return (
        artists_level is FavoritesRequestLevel.EXPLICIT,
        tracks_level is FavoritesRequestLevel.EXPLICIT,
    )


def favorite_categories_mentioned(prompt: str) -> tuple[bool, bool]:
    """Whether the prompt references bookmarked favorites at all (any tier)."""
    artists_level, tracks_level = favorite_categories_requested_levels(prompt)
    return artists_level is not FavoritesRequestLevel.NONE, tracks_level is not FavoritesRequestLevel.NONE


def activate_favorite_artist_allowlist(artists: list[str]) -> None:
    """Set the hard artist allowlist for the current generation request/stage."""
    _FAVORITE_ARTIST_ALLOWLIST.set(tuple(dict.fromkeys(name for name in artists if name)))


def active_favorite_artist_allowlist() -> tuple[str, ...]:
    return _FAVORITE_ARTIST_ALLOWLIST.get()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _clean_name(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()[:MAX_FAVORITE_NAME_LENGTH]


def _empty_state() -> dict[str, list[dict[str, Any]]]:
    return {"artists": [], "tracks": []}


def _state() -> dict[str, list[dict[str, Any]]]:
    raw = read_json_object(FAVORITES_PATH)
    artists = raw.get("artists")
    tracks = raw.get("tracks")
    return {
        "artists": [entry for entry in artists if isinstance(entry, dict)]
        if isinstance(artists, list)
        else [],
        "tracks": [entry for entry in tracks if isinstance(entry, dict)]
        if isinstance(tracks, list)
        else [],
    }


def _save(state: dict[str, list[dict[str, Any]]]) -> None:
    write_secure_json(
        FAVORITES_PATH,
        state,
        temporary_path=FAVORITES_PATH.with_suffix(".tmp"),
    )


def list_favorite_artists() -> list[dict[str, Any]]:
    return _state()["artists"]


def list_favorite_tracks() -> list[dict[str, Any]]:
    return _state()["tracks"]


def add_favorite_artist(name: str) -> dict[str, list[dict[str, Any]]]:
    label = _clean_name(name)
    if not label:
        raise ValueError("Enter an artist name first.")

    state = _state()
    if any(entry.get("name", "").casefold() == label.casefold() for entry in state["artists"]):
        raise ValueError("This artist is already a favorite.")
    if len(state["artists"]) >= MAX_FAVORITE_ARTISTS:
        raise ValueError(f"You can have at most {MAX_FAVORITE_ARTISTS} favorite artists.")

    state["artists"].append({"name": label, "added_at": _now()})
    _save(state)
    return state


def remove_favorite_artist(name: str) -> dict[str, list[dict[str, Any]]]:
    key = _clean_name(name).casefold()
    state = _state()
    state["artists"] = [
        entry for entry in state["artists"] if entry.get("name", "").casefold() != key
    ]
    _save(state)
    return state


def add_favorite_track(track: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    video_id = str(track.get("video_id") or "").strip()
    title = _clean_name(track.get("title"))
    artists = _clean_name(track.get("artists"))
    if not video_id or not title or not artists:
        raise ValueError("A favorite track needs a video ID, title and artist.")

    state = _state()
    if any(entry.get("video_id") == video_id for entry in state["tracks"]):
        raise ValueError("This track is already a favorite.")
    if len(state["tracks"]) >= MAX_FAVORITE_TRACKS:
        raise ValueError(f"You can have at most {MAX_FAVORITE_TRACKS} favorite tracks.")

    state["tracks"].append(
        {
            "video_id": video_id,
            "title": title,
            "artists": artists,
            "album": _clean_name(track.get("album")),
            "thumbnail_url": str(track.get("thumbnail_url") or "").strip(),
            "added_at": _now(),
        }
    )
    _save(state)
    return state


def remove_favorite_track(video_id: str) -> dict[str, list[dict[str, Any]]]:
    key = str(video_id or "").strip()
    state = _state()
    state["tracks"] = [entry for entry in state["tracks"] if entry.get("video_id") != key]
    _save(state)
    return state


def favorite_artist_names(limit: int = 40) -> list[str]:
    return [entry["name"] for entry in list_favorite_artists()[:limit] if entry.get("name")]


def favorite_track_summaries(limit: int = 40) -> list[dict[str, str]]:
    return [
        {"title": entry.get("title", ""), "artists": entry.get("artists", "")}
        for entry in list_favorite_tracks()[:limit]
        if entry.get("title") and entry.get("artists")
    ]


def _library_lookup(
    artist_names: list[str], video_ids: list[str]
) -> tuple[dict[str, int], dict[str, str], dict[str, int]]:
    """Scan the library once for every favorite at once -- counting, per favorite
    artist and track, how many playlists it appears in, and picking a
    representative thumbnail for each favorite artist from one of its tracks
    (favorite artists have no thumbnail of their own, only a name)."""
    artist_keys = {name.casefold() for name in artist_names if name}
    video_id_set = {video_id for video_id in video_ids if video_id}
    artist_counts: dict[str, int] = dict.fromkeys(artist_keys, 0)
    artist_thumbnails: dict[str, str] = {}
    track_counts: dict[str, int] = dict.fromkeys(video_id_set, 0)
    if not DATABASE_PATH.exists() or (not artist_keys and not video_id_set):
        return artist_counts, artist_thumbnails, track_counts

    connection = sqlite3.connect(DATABASE_PATH, timeout=5)
    try:
        rows = connection.execute("SELECT playlist_json FROM playlists").fetchall()
    finally:
        connection.close()

    for (raw,) in rows:
        try:
            playlist = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            continue
        if not isinstance(playlist, dict):
            continue

        matched_artist_keys: set[str] = set()
        matched_video_ids: set[str] = set()
        for track in playlist.get("tracks") or []:
            if not isinstance(track, dict):
                continue
            video_id = str(track.get("video_id", "")).strip()
            if video_id in video_id_set:
                matched_video_ids.add(video_id)
            thumbnail = str(track.get("thumbnail_url", "")).strip()
            for name in split_artist_credit(str(track.get("artists", ""))):
                key = name.casefold()
                if key in artist_keys:
                    matched_artist_keys.add(key)
                    if thumbnail and key not in artist_thumbnails:
                        artist_thumbnails[key] = thumbnail

        for key in matched_artist_keys:
            artist_counts[key] += 1
        for video_id in matched_video_ids:
            track_counts[video_id] += 1

    return artist_counts, artist_thumbnails, track_counts


def _with_playlist_counts(
    state: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    artist_counts, artist_thumbnails, track_counts = _library_lookup(
        [entry.get("name", "") for entry in state["artists"]],
        [entry.get("video_id", "") for entry in state["tracks"]],
    )
    return {
        "artists": [
            {
                **entry,
                "playlist_count": artist_counts.get(str(entry.get("name", "")).casefold(), 0),
                "thumbnail_url": artist_thumbnails.get(str(entry.get("name", "")).casefold(), ""),
            }
            for entry in state["artists"]
        ],
        "tracks": [
            {**entry, "playlist_count": track_counts.get(str(entry.get("video_id", "")), 0)}
            for entry in state["tracks"]
        ],
    }


router = APIRouter(prefix="/favorites", tags=["favorites"])


class FavoriteArtistIn(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_FAVORITE_NAME_LENGTH)


class FavoriteTrackIn(BaseModel):
    video_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=300)
    artists: str = Field(min_length=1, max_length=300)
    album: str = Field(default="", max_length=300)
    thumbnail_url: str = Field(default="", max_length=1000)


@router.get("")
async def get_favorites() -> dict[str, list[dict[str, Any]]]:
    return _with_playlist_counts(_state())


@router.post("/artists")
async def post_favorite_artist(request: FavoriteArtistIn) -> dict[str, list[dict[str, Any]]]:
    try:
        return _with_playlist_counts(add_favorite_artist(request.name))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.delete("/artists")
async def delete_favorite_artist(name: str) -> dict[str, list[dict[str, Any]]]:
    return _with_playlist_counts(remove_favorite_artist(name))


@router.post("/tracks")
async def post_favorite_track(request: FavoriteTrackIn) -> dict[str, list[dict[str, Any]]]:
    try:
        return _with_playlist_counts(add_favorite_track(request.model_dump()))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.delete("/tracks/{video_id}")
async def delete_favorite_track(video_id: str) -> dict[str, list[dict[str, Any]]]:
    return _with_playlist_counts(remove_favorite_track(video_id))
