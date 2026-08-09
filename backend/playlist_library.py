"""Persistent local playlist library backed by SQLite."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import suppress
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, field_validator

from backend.config import DATA_DIR, load_config
from backend.playlist_tags import normalize_playlist_tags, suggest_playlist_tags

DATABASE_PATH = DATA_DIR / "playlists.db"
SCHEMA_VERSION = 1
SortOrder = Literal["updated_desc", "created_desc", "title_asc", "title_desc"]
LOGGER = logging.getLogger("playlistmuse.library")

router = APIRouter(prefix="/library/playlists", tags=["playlist-library"])


class PlaylistWriteRequest(BaseModel):
    """Playlist document and the generation settings needed for later editing."""

    model_config = ConfigDict(extra="forbid")

    playlist: dict[str, Any]
    generation_request: dict[str, Any] | None = None

    @field_validator("playlist")
    @classmethod
    def validate_playlist(cls, value: dict[str, Any]) -> dict[str, Any]:
        playlist = dict(value)
        tracks = playlist.get("tracks")
        if not isinstance(tracks, list) or not tracks:
            raise ValueError("A playlist must contain at least one track.")
        if len(tracks) > 300:
            raise ValueError("A playlist cannot contain more than 300 tracks.")
        if any(not isinstance(track, dict) for track in tracks):
            raise ValueError("Every playlist track must be an object.")

        playlist.pop("library_id", None)
        playlist["name"] = (
            str(playlist.get("name", "")).strip()[:100] or "Untitled playlist"
        )
        playlist["description"] = str(playlist.get("description", "")).strip()[:2000]
        playlist["prompt"] = str(playlist.get("prompt", "")).strip()[:1950]
        if "tags" in playlist:
            playlist["tags"] = normalize_playlist_tags(playlist.get("tags"))
        return playlist


class PlaylistNotFoundError(LookupError):
    """Raised when a requested library record does not exist."""


class PlaylistLibrary:
    """SQLite repository for complete, atomic playlist documents."""

    _SORT_SQL: dict[SortOrder, str] = {
        "updated_desc": "updated_at DESC, created_at DESC",
        "created_desc": "created_at DESC, updated_at DESC",
        "title_asc": "name COLLATE NOCASE ASC, updated_at DESC",
        "title_desc": "name COLLATE NOCASE DESC, updated_at DESC",
    }

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            current = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current > SCHEMA_VERSION:
                raise RuntimeError(
                    "The playlist library was created by a newer PlaylistMuse version."
                )
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS playlists (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    prompt TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL CHECK (status IN ('draft', 'published')),
                    track_count INTEGER NOT NULL,
                    youtube_playlist_id TEXT,
                    youtube_playlist_url TEXT,
                    playlist_json TEXT NOT NULL,
                    generation_request_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_playlists_updated_at "
                "ON playlists(updated_at DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_playlists_name "
                "ON playlists(name COLLATE NOCASE)"
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        with suppress(OSError):
            self.database_path.chmod(0o600)

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat(timespec="seconds")

    @staticmethod
    def _publication(playlist: dict[str, Any]) -> tuple[str, str | None, str | None]:
        published = playlist.get("youtube_playlist")
        if not isinstance(published, dict):
            return "draft", None, None
        remote_id = str(published.get("playlist_id") or published.get("id") or "").strip()
        remote_url = str(published.get("url") or "").strip()
        if not remote_id and not remote_url:
            return "draft", None, None
        return "published", remote_id or None, remote_url or None

    @staticmethod
    def _json(value: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _decode(value: str | None, fallback: Any) -> Any:
        try:
            return json.loads(value) if value else fallback
        except json.JSONDecodeError:
            return fallback

    @staticmethod
    def _thumbnails(playlist: dict[str, Any]) -> list[str]:
        urls: list[str] = []
        for track in playlist.get("tracks", []):
            if isinstance(track, dict):
                url = str(track.get("thumbnail_url") or "").strip()
                if url and url not in urls:
                    urls.append(url)
            if len(urls) == 4:
                break
        return urls

    def _record(self, row: sqlite3.Row, *, include_document: bool) -> dict[str, Any]:
        playlist = self._decode(row["playlist_json"], {})
        if not isinstance(playlist, dict):
            playlist = {}
        tags = normalize_playlist_tags(playlist.get("tags"))
        playlist["tags"] = tags
        record = {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "prompt": row["prompt"],
            "status": row["status"],
            "track_count": row["track_count"],
            "thumbnail_urls": self._thumbnails(playlist),
            "tags": tags,
            "youtube_playlist_id": row["youtube_playlist_id"],
            "youtube_playlist_url": row["youtube_playlist_url"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        if include_document:
            record["playlist"] = playlist
            record["generation_request"] = self._decode(
                row["generation_request_json"], None
            )
        return record

    def create(
        self,
        playlist: dict[str, Any],
        generation_request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        playlist_id = str(uuid4())
        timestamp = self._now()
        publication, remote_id, remote_url = self._publication(playlist)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO playlists (
                    id, name, description, prompt, status, track_count,
                    youtube_playlist_id, youtube_playlist_url,
                    playlist_json, generation_request_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    playlist_id,
                    playlist["name"],
                    playlist.get("description", ""),
                    playlist.get("prompt", ""),
                    publication,
                    len(playlist["tracks"]),
                    remote_id,
                    remote_url,
                    self._json(playlist),
                    self._json(generation_request),
                    timestamp,
                    timestamp,
                ),
            )
        return self.get(playlist_id)

    def list(self, sort: SortOrder = "updated_desc") -> list[dict[str, Any]]:
        order = self._SORT_SQL[sort]
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM playlists ORDER BY {order}"  # noqa: S608
            ).fetchall()
        return [self._record(row, include_document=False) for row in rows]

    def get(self, playlist_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM playlists WHERE id = ?", (playlist_id,)
            ).fetchone()
        if row is None:
            raise PlaylistNotFoundError(playlist_id)
        return self._record(row, include_document=True)

    def update(
        self,
        playlist_id: str,
        playlist: dict[str, Any],
        generation_request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        updated_playlist = dict(playlist)
        with self._connect() as connection:
            existing_row = connection.execute(
                "SELECT playlist_json FROM playlists WHERE id = ?", (playlist_id,)
            ).fetchone()
            if existing_row is None:
                raise PlaylistNotFoundError(playlist_id)

            if "tags" not in updated_playlist:
                existing_playlist = self._decode(existing_row["playlist_json"], {})
                if isinstance(existing_playlist, dict) and "tags" in existing_playlist:
                    updated_playlist["tags"] = normalize_playlist_tags(
                        existing_playlist.get("tags")
                    )

            publication, remote_id, remote_url = self._publication(updated_playlist)
            connection.execute(
                """
                UPDATE playlists
                SET name = ?, description = ?, prompt = ?, status = ?, track_count = ?,
                    youtube_playlist_id = ?, youtube_playlist_url = ?,
                    playlist_json = ?, generation_request_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    updated_playlist["name"],
                    updated_playlist.get("description", ""),
                    updated_playlist.get("prompt", ""),
                    publication,
                    len(updated_playlist["tracks"]),
                    remote_id,
                    remote_url,
                    self._json(updated_playlist),
                    self._json(generation_request),
                    self._now(),
                    playlist_id,
                ),
            )
        return self.get(playlist_id)

    def duplicate(self, playlist_id: str) -> dict[str, Any]:
        source = self.get(playlist_id)
        playlist = deepcopy(source["playlist"])
        playlist.pop("library_id", None)
        playlist.pop("youtube_playlist", None)
        name = str(playlist.get("name") or "Untitled playlist").strip()
        playlist["name"] = f"{name} (copy)"[:100]
        return self.create(playlist, deepcopy(source["generation_request"]))

    def delete(self, playlist_id: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM playlists WHERE id = ?", (playlist_id,)
            )
        if cursor.rowcount == 0:
            raise PlaylistNotFoundError(playlist_id)


_library: PlaylistLibrary | None = None


def get_library() -> PlaylistLibrary:
    """Return the process-wide repository, initializing it on first use."""
    global _library
    if _library is None:
        _library = PlaylistLibrary(DATABASE_PATH)
    return _library


def _not_found(playlist_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=f"Playlist {playlist_id} was not found in the local library.",
    )


@router.get("")
async def list_playlists(
    sort: Annotated[SortOrder, Query()] = "updated_desc",
) -> dict[str, list[dict[str, Any]]]:
    return {"items": get_library().list(sort)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_playlist(request: PlaylistWriteRequest) -> dict[str, Any]:
    library = get_library()
    created = library.create(request.playlist, request.generation_request)
    if "tags" in request.playlist:
        return created

    try:
        tags = await suggest_playlist_tags(load_config(), created["playlist"])
    except Exception as error:
        LOGGER.warning(
            "Automatic playlist tagging skipped id=%s error=%s",
            created["id"],
            type(error).__name__,
        )
        return created

    playlist = deepcopy(created["playlist"])
    playlist["tags"] = tags
    return library.update(created["id"], playlist, created["generation_request"])


@router.get("/{playlist_id}")
async def get_playlist(playlist_id: str) -> dict[str, Any]:
    try:
        return get_library().get(playlist_id)
    except PlaylistNotFoundError as error:
        raise _not_found(playlist_id) from error


@router.put("/{playlist_id}")
async def update_playlist(
    playlist_id: str,
    request: PlaylistWriteRequest,
) -> dict[str, Any]:
    try:
        return get_library().update(
            playlist_id, request.playlist, request.generation_request
        )
    except PlaylistNotFoundError as error:
        raise _not_found(playlist_id) from error


@router.post("/{playlist_id}/tags/suggest")
async def suggest_tags(playlist_id: str) -> dict[str, Any]:
    try:
        record = get_library().get(playlist_id)
    except PlaylistNotFoundError as error:
        raise _not_found(playlist_id) from error

    try:
        tags = await suggest_playlist_tags(load_config(), record["playlist"])
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail="Playlist tags could not be generated. Please try again.",
        ) from error

    playlist = deepcopy(record["playlist"])
    playlist["tags"] = tags
    return get_library().update(
        playlist_id,
        playlist,
        record["generation_request"],
    )


@router.post("/{playlist_id}/duplicate", status_code=status.HTTP_201_CREATED)
async def duplicate_playlist(playlist_id: str) -> dict[str, Any]:
    try:
        return get_library().duplicate(playlist_id)
    except PlaylistNotFoundError as error:
        raise _not_found(playlist_id) from error


@router.delete("/{playlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_playlist(playlist_id: str) -> Response:
    try:
        get_library().delete(playlist_id)
    except PlaylistNotFoundError as error:
        raise _not_found(playlist_id) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
