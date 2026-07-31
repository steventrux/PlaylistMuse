"""Orchestrate YouTube playlist publishing and optional cover upload."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from backend.playlist_cover import PlaylistCoverError, upload_playlist_cover
from backend.youtube_publish import (
    REQUEST_TIMEOUT,
    _access_token,
    create_youtube_playlist as publish_playlist,
)

LOGGER = logging.getLogger("playlistmuse.youtube.cover")
_COVER_WARNING = (
    "The playlist was created, but YouTube did not accept the mosaic cover."
)


def _append_warning(result: dict[str, Any], warning: str) -> None:
    current = str(result.get("warning") or "").strip()
    result["warning"] = f"{current} {warning}".strip()


def _upload_cover_sync(playlist_id: str, thumbnail_urls: list[str]) -> None:
    with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
        upload_playlist_cover(
            client,
            playlist_id,
            thumbnail_urls,
            _access_token,
        )


async def create_youtube_playlist(
    title: str,
    description: str,
    privacy_status: str,
    video_ids: list[str],
    thumbnail_urls: list[str],
) -> dict[str, Any]:
    """Publish a playlist, then attach its mosaic without risking the playlist."""

    result = await publish_playlist(
        title,
        description,
        privacy_status,
        video_ids,
    )
    result["cover_uploaded"] = False

    playlist_id = str(result.get("playlist_id") or "").strip()
    if not playlist_id or len(thumbnail_urls) != 4:
        _append_warning(result, _COVER_WARNING)
        return result

    try:
        await asyncio.to_thread(_upload_cover_sync, playlist_id, thumbnail_urls)
        result["cover_uploaded"] = True
        LOGGER.info("YouTube playlist cover uploaded playlist_id=%s", playlist_id)
    except PlaylistCoverError as error:
        LOGGER.warning(
            "YouTube playlist cover upload failed playlist_id=%s error=%s",
            playlist_id,
            error,
        )
        _append_warning(result, _COVER_WARNING)
    except Exception:
        LOGGER.exception(
            "Unexpected YouTube playlist cover failure playlist_id=%s",
            playlist_id,
        )
        _append_warning(result, _COVER_WARNING)

    return result
