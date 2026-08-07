"""Keep local publication state aligned with deleted YouTube playlists."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from backend.playlist_library import PlaylistLibrary, get_library
from backend.youtube_publish import YOUTUBE_API_BASE, _access_token

LOGGER = logging.getLogger("playlistmuse.playlist.publication-sync")
STATUS_REQUEST_TIMEOUT = 5.0
YOUTUBE_PLAYLIST_BATCH_SIZE = 50


def _published_remote_ids(records: list[dict[str, Any]]) -> list[str]:
    return list(
        dict.fromkeys(
            str(record.get("youtube_playlist_id") or "").strip()
            for record in records
            if record.get("status") == "published"
            and str(record.get("youtube_playlist_id") or "").strip()
        )
    )


def _send_playlist_status_request(
    client: httpx.Client,
    params: dict[str, str],
    *,
    force_refresh: bool = False,
) -> httpx.Response:
    return client.get(
        f"{YOUTUBE_API_BASE}/playlists",
        params=params,
        headers={
            "Authorization": f"Bearer {_access_token(force_refresh=force_refresh)}",
            "Accept": "application/json",
        },
    )


def _fetch_existing_youtube_playlist_ids(playlist_ids: list[str]) -> set[str]:
    """Return IDs that YouTube still reports as existing for the connected account."""
    existing: set[str] = set()
    with httpx.Client(timeout=STATUS_REQUEST_TIMEOUT) as client:
        for start in range(0, len(playlist_ids), YOUTUBE_PLAYLIST_BATCH_SIZE):
            batch = playlist_ids[start : start + YOUTUBE_PLAYLIST_BATCH_SIZE]
            params = {
                "part": "id",
                "id": ",".join(batch),
                "maxResults": str(len(batch)),
            }
            response = _send_playlist_status_request(client, params)
            if response.status_code == 401:
                response = _send_playlist_status_request(
                    client,
                    params,
                    force_refresh=True,
                )
            response.raise_for_status()
            payload = response.json()
            items = payload.get("items", []) if isinstance(payload, dict) else []
            for item in items:
                if not isinstance(item, dict):
                    continue
                playlist_id = str(item.get("id") or "").strip()
                if playlist_id:
                    existing.add(playlist_id)
    return existing


def _demote_missing_playlist(
    library: PlaylistLibrary,
    record: dict[str, Any],
    remote_id: str,
) -> bool:
    """Remove stale YouTube metadata without changing the playlist update time."""
    playlist_id = str(record["id"])
    with library._connect() as connection:
        row = connection.execute(
            """
            SELECT status, youtube_playlist_id, playlist_json
            FROM playlists
            WHERE id = ?
            """,
            (playlist_id,),
        ).fetchone()
        if row is None or row["status"] != "published":
            return False
        if str(row["youtube_playlist_id"] or "").strip() != remote_id:
            return False

        playlist = library._decode(row["playlist_json"], {})
        if not isinstance(playlist, dict):
            return False
        playlist.pop("youtube_playlist", None)

        cursor = connection.execute(
            """
            UPDATE playlists
            SET status = 'draft',
                youtube_playlist_id = NULL,
                youtube_playlist_url = NULL,
                playlist_json = ?
            WHERE id = ?
              AND status = 'published'
              AND youtube_playlist_id = ?
            """,
            (library._json(playlist), playlist_id, remote_id),
        )
    return cursor.rowcount > 0


async def reconcile_deleted_youtube_playlists(
    library: PlaylistLibrary | None = None,
) -> int:
    """Demote published local playlists only when YouTube confirms they are gone."""
    repository = library or get_library()
    records = repository.list()
    remote_ids = _published_remote_ids(records)
    if not remote_ids:
        return 0

    try:
        existing = await asyncio.to_thread(
            _fetch_existing_youtube_playlist_ids,
            remote_ids,
        )
    except Exception as error:
        LOGGER.warning(
            "Skipping YouTube publication reconciliation because verification failed: %s",
            error,
        )
        return 0

    changed = 0
    for record in records:
        remote_id = str(record.get("youtube_playlist_id") or "").strip()
        if record.get("status") != "published" or not remote_id:
            continue
        if remote_id in existing:
            continue
        if _demote_missing_playlist(repository, record, remote_id):
            changed += 1

    if changed:
        LOGGER.info("Demoted %s deleted YouTube playlist(s) to draft", changed)
    return changed
