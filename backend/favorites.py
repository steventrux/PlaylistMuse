"""Global list of favorite artists and tracks, used to bias future generations."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
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
