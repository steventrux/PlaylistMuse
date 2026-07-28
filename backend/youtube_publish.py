"""Robust YouTube Music playlist publishing.

A playlist is created empty first, tracks are appended in order, and a failed
batch is retried one track at a time. This prevents one unavailable video ID
from aborting the entire playlist.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import Any

from backend.youtube_account import YouTubeAccountError, _ytmusic_client

LOGGER = logging.getLogger("playlistmuse.youtube.publish")
BATCH_SIZE = 10


def _diagnostic_id() -> str:
    return uuid.uuid4().hex[:8].upper()


def _safe_log_text(value: Any) -> str:
    """Return a compact diagnostic string without OAuth secrets."""

    text = repr(value)
    patterns = (
        r"(?i)(access_token|refresh_token|client_secret|authorization)[\s'\":=]+[^,}\s]+",
        r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]+",
    )
    for pattern in patterns:
        text = re.sub(pattern, r"\1=[REDACTED]" if "(" in pattern else "Bearer [REDACTED]", text)
    return text[:1200]


def _response_succeeded(result: Any) -> bool:
    if isinstance(result, str):
        return "SUCCEEDED" in result.upper()
    if isinstance(result, dict):
        if result.get("playlistId") or result.get("id"):
            return True
        return "SUCCEEDED" in str(result.get("status", "")).upper()
    return False


def _playlist_id(result: Any) -> str | None:
    if isinstance(result, str):
        value = result.strip()
        return value or None
    if isinstance(result, dict):
        value = str(result.get("playlistId") or result.get("id") or "").strip()
        return value or None
    return None


def _delete_quietly(client: Any, playlist_id: str) -> None:
    try:
        client.delete_playlist(playlist_id)
    except Exception:
        pass


def _add_batch(client: Any, playlist_id: str, video_ids: list[str]) -> tuple[list[str], list[str]]:
    """Add a batch, retrying individual tracks if the batch is rejected."""

    try:
        result = client.add_playlist_items(
            playlistId=playlist_id,
            videoIds=video_ids,
            duplicates=False,
        )
        if _response_succeeded(result):
            return list(video_ids), []
    except Exception:
        pass

    added: list[str] = []
    skipped: list[str] = []
    for video_id in video_ids:
        try:
            result = client.add_playlist_items(
                playlistId=playlist_id,
                videoIds=[video_id],
                duplicates=False,
            )
            if _response_succeeded(result):
                added.append(video_id)
            else:
                skipped.append(video_id)
        except Exception:
            skipped.append(video_id)
    return added, skipped


def _create_playlist_sync(
    title: str,
    description: str,
    privacy_status: str,
    video_ids: list[str],
) -> dict[str, Any]:
    unique_video_ids = list(
        dict.fromkeys(video_id.strip() for video_id in video_ids if video_id.strip())
    )
    if not unique_video_ids:
        raise YouTubeAccountError("The playlist contains no valid YouTube Music tracks.")

    diagnostic = _diagnostic_id()
    client = _ytmusic_client()

    # Creating the container separately isolates account/privacy failures from
    # unavailable tracks. PRIVATE is the least restrictive initial state.
    try:
        create_result = client.create_playlist(
            title=title.strip(),
            description=description.strip(),
            privacy_status="PRIVATE",
            video_ids=None,
        )
    except Exception as error:
        LOGGER.exception(
            "YouTube playlist create failed [%s]: %s",
            diagnostic,
            _safe_log_text(error),
        )
        raise YouTubeAccountError(
            "The connected Google account could not create a YouTube Music playlist. "
            f"Diagnostic reference: {diagnostic}."
        ) from error

    playlist_id = _playlist_id(create_result)
    if not playlist_id:
        LOGGER.error(
            "YouTube playlist create returned no ID [%s]: %s",
            diagnostic,
            _safe_log_text(create_result),
        )
        raise YouTubeAccountError(
            "YouTube Music did not return a playlist ID. "
            f"Diagnostic reference: {diagnostic}."
        )

    added: list[str] = []
    skipped: list[str] = []
    for start in range(0, len(unique_video_ids), BATCH_SIZE):
        batch = unique_video_ids[start : start + BATCH_SIZE]
        batch_added, batch_skipped = _add_batch(client, playlist_id, batch)
        added.extend(batch_added)
        skipped.extend(batch_skipped)

    if not added:
        _delete_quietly(client, playlist_id)
        LOGGER.error(
            "YouTube rejected every track [%s], requested=%d",
            diagnostic,
            len(unique_video_ids),
        )
        raise YouTubeAccountError(
            "YouTube Music created the playlist container but rejected every track. "
            f"Diagnostic reference: {diagnostic}."
        )

    applied_privacy = "PRIVATE"
    privacy_warning = ""
    if privacy_status != "PRIVATE":
        try:
            edit_result = client.edit_playlist(
                playlistId=playlist_id,
                privacyStatus=privacy_status,
            )
            if _response_succeeded(edit_result):
                applied_privacy = privacy_status
            else:
                privacy_warning = "The playlist was kept private because YouTube rejected the selected privacy."
                LOGGER.warning(
                    "YouTube privacy update failed [%s]: %s",
                    diagnostic,
                    _safe_log_text(edit_result),
                )
        except Exception as error:
            privacy_warning = "The playlist was kept private because YouTube rejected the selected privacy."
            LOGGER.warning(
                "YouTube privacy update exception [%s]: %s",
                diagnostic,
                _safe_log_text(error),
            )

    warning_parts: list[str] = []
    if skipped:
        warning_parts.append(
            f"YouTube skipped {len(skipped)} of {len(unique_video_ids)} tracks that could not be added."
        )
    if privacy_warning:
        warning_parts.append(privacy_warning)

    return {
        "playlist_id": playlist_id,
        "title": title.strip(),
        "track_count": len(added),
        "requested_track_count": len(unique_video_ids),
        "skipped_count": len(skipped),
        "privacy_status": applied_privacy,
        "warning": " ".join(warning_parts) or None,
        "url": f"https://music.youtube.com/playlist?list={playlist_id}",
    }


async def create_youtube_playlist(
    title: str,
    description: str,
    privacy_status: str,
    video_ids: list[str],
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _create_playlist_sync,
        title,
        description,
        privacy_status,
        video_ids,
    )
