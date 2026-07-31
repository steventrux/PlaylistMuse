"""Reliable playlist publishing through the official YouTube Data API.

The OAuth device flow already grants the ``youtube`` scope required by the
official playlists and playlistItems endpoints. A private playlist is created
first, tracks are appended one at a time in order, then the requested privacy
is applied. Invalid or unavailable videos do not abort the whole playlist.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from typing import Any

import httpx

from backend.storage import read_json_object, write_secure_json
from backend.youtube_account import (
    YOUTUBE_TOKEN_PATH,
    YouTubeAccountError,
    _oauth_credentials,
)

LOGGER = logging.getLogger("playlistmuse.youtube.publish")
YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
REQUEST_TIMEOUT = 30.0
TRACK_INSERT_MAX_ATTEMPTS = 2
TRACK_INSERT_RETRY_DELAY_SECONDS = 1.0
_SENSITIVE_FIELD_RE = re.compile(
    r'(?i)(access_token|refresh_token|client_secret|authorization)[\s\'":=]+[^,}\s]+'
)
_BEARER_TOKEN_RE = re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]+")
_SKIPPABLE_TRACK_REASONS = {
    "videonotfound",
    "invalidresourcetype",
    "videoalreadyinplaylist",
}
_RETRYABLE_TRACK_ABORT_REASONS = {
    "serviceunavailable",
    "aborted",
}


class _GoogleApiError(RuntimeError):
    def __init__(self, status_code: int, reason: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason
        self.message = message


def _diagnostic_id() -> str:
    return uuid.uuid4().hex[:8].upper()


def _safe_log_text(value: Any) -> str:
    text = repr(value)
    text = _SENSITIVE_FIELD_RE.sub(r"\1=[REDACTED]", text)
    text = _BEARER_TOKEN_RE.sub("Bearer [REDACTED]", text)
    return text[:1400]


def _token_is_current(token: dict[str, Any]) -> bool:
    return bool(
        str(token.get("access_token", "")).strip()
        and int(token.get("expires_at", 0) or 0) > int(time.time()) + 60
    )


def _refresh_access_token() -> str:
    token = read_json_object(YOUTUBE_TOKEN_PATH)
    refresh_token = str(token.get("refresh_token", "")).strip()
    if not refresh_token:
        raise YouTubeAccountError("Reconnect the YouTube Music account before publishing.")

    try:
        fresh = _oauth_credentials().refresh_token(refresh_token)
    except Exception as error:
        raise YouTubeAccountError(
            "The Google authorization expired. Disconnect and reconnect the account."
        ) from error

    access_token = str(fresh.get("access_token", "")).strip()
    if not access_token:
        raise YouTubeAccountError("Google did not return a valid access token.")

    access_expires_in = max(1, int(fresh.get("expires_in", 3600)))
    token["access_token"] = access_token
    token["expires_at"] = int(time.time()) + access_expires_in
    token["token_type"] = (
        str(fresh.get("token_type", token.get("token_type", "Bearer"))) or "Bearer"
    )
    if fresh.get("scope"):
        token["scope"] = fresh["scope"]
    write_secure_json(YOUTUBE_TOKEN_PATH, token)
    return access_token


def _access_token(force_refresh: bool = False) -> str:
    token = read_json_object(YOUTUBE_TOKEN_PATH)
    if not force_refresh and _token_is_current(token):
        return str(token["access_token"])
    return _refresh_access_token()


def _parse_google_error(response: httpx.Response) -> _GoogleApiError:
    reason = "unknown"
    message = f"HTTP {response.status_code}"
    try:
        payload = response.json()
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        message = str(error.get("message") or message)
        errors = error.get("errors", [])
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            reason = str(errors[0].get("reason") or reason)
        elif error.get("status"):
            reason = str(error["status"])
    except Exception:
        pass
    return _GoogleApiError(response.status_code, reason, message)


def _request(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    params: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
) -> httpx.Response:
    url = f"{YOUTUBE_API_BASE}/{path.lstrip('/')}"

    def send(token: str) -> httpx.Response:
        return client.request(
            method,
            url,
            params=params,
            json=json_body,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )

    response = send(_access_token())
    if response.status_code == 401:
        response = send(_access_token(force_refresh=True))
    if response.is_error:
        raise _parse_google_error(response)
    return response


def _public_error(error: _GoogleApiError, diagnostic: str) -> YouTubeAccountError:
    reason = error.reason.lower()
    if reason in {"youtubesignuprequired", "channelnotfound"}:
        return YouTubeAccountError(
            "This Google account does not have an active YouTube channel. Open YouTube, "
            f"create or select a channel, then reconnect PlaylistMuse. Reference: {diagnostic}."
        )
    if reason in {
        "playlistforbidden",
        "playlistitemsnotaccessible",
        "insufficientpermissions",
        "forbidden",
    } or error.status_code == 403:
        if "quota" in reason or "limit" in reason:
            return YouTubeAccountError(
                "The YouTube Data API quota or daily playlist limit has been reached. "
                f"Reference: {diagnostic}."
            )
        return YouTubeAccountError(
            "The connected account is not authorized to create playlists. Verify that "
            "YouTube Data API v3 is enabled, then disconnect and reconnect the account. "
            f"Reference: {diagnostic}."
        )
    if reason in {"quotaexceeded", "dailylimitexceeded", "ratelimitexceeded"}:
        return YouTubeAccountError(
            "The YouTube Data API quota has been reached. Try again after the quota resets. "
            f"Reference: {diagnostic}."
        )
    if reason == "maxplaylistexceeded":
        return YouTubeAccountError(
            "This YouTube channel has reached its maximum number of playlists. "
            f"Reference: {diagnostic}."
        )
    if error.status_code == 401:
        return YouTubeAccountError(
            "The Google authorization is no longer valid. Disconnect and reconnect the account. "
            f"Reference: {diagnostic}."
        )
    return YouTubeAccountError(
        "YouTube could not create the playlist. "
        f"Diagnostic reference: {diagnostic}."
    )


def _create_empty_playlist(
    client: httpx.Client,
    title: str,
    description: str,
) -> str:
    response = _request(
        client,
        "POST",
        "playlists",
        params={"part": "snippet,status"},
        json_body={
            "snippet": {
                "title": title,
                "description": description,
            },
            "status": {"privacyStatus": "private"},
        },
    )
    payload = response.json()
    playlist_id = str(payload.get("id", "")).strip() if isinstance(payload, dict) else ""
    if not playlist_id:
        raise _GoogleApiError(502, "missingPlaylistId", "YouTube returned no playlist ID")
    return playlist_id


def _normalize_error_reason(reason: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", reason.casefold())


def _is_retryable_track_insert_error(error: _GoogleApiError) -> bool:
    return bool(
        error.status_code == 409
        and _normalize_error_reason(error.reason) in _RETRYABLE_TRACK_ABORT_REASONS
        and "operation was aborted" in error.message.casefold()
    )


def _add_track(client: httpx.Client, playlist_id: str, video_id: str) -> None:
    for attempt in range(1, TRACK_INSERT_MAX_ATTEMPTS + 1):
        try:
            _request(
                client,
                "POST",
                "playlistItems",
                params={"part": "snippet"},
                json_body={
                    "snippet": {
                        "playlistId": playlist_id,
                        "resourceId": {
                            "kind": "youtube#video",
                            "videoId": video_id,
                        },
                    }
                },
            )
            return
        except _GoogleApiError as error:
            if (
                attempt >= TRACK_INSERT_MAX_ATTEMPTS
                or not _is_retryable_track_insert_error(error)
            ):
                raise
            LOGGER.warning(
                "YouTube track insert aborted; retrying attempt=%s/%s video_id=%s",
                attempt + 1,
                TRACK_INSERT_MAX_ATTEMPTS,
                video_id,
            )
            time.sleep(TRACK_INSERT_RETRY_DELAY_SECONDS)


def _set_privacy(
    client: httpx.Client,
    playlist_id: str,
    title: str,
    description: str,
    privacy_status: str,
) -> None:
    _request(
        client,
        "PUT",
        "playlists",
        params={"part": "snippet,status"},
        json_body={
            "id": playlist_id,
            "snippet": {
                "title": title,
                "description": description,
            },
            "status": {"privacyStatus": privacy_status.lower()},
        },
    )


def _delete_quietly(client: httpx.Client, playlist_id: str) -> None:
    try:
        _request(client, "DELETE", "playlists", params={"id": playlist_id})
    except Exception:
        pass


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
        raise YouTubeAccountError("The playlist contains no valid YouTube tracks.")

    normalized_title = title.strip()
    normalized_description = description.strip()
    diagnostic = _diagnostic_id()

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            playlist_id = _create_empty_playlist(client, normalized_title, normalized_description)

            added: list[str] = []
            skipped: list[str] = []
            for video_id in unique_video_ids:
                try:
                    _add_track(client, playlist_id, video_id)
                    added.append(video_id)
                except _GoogleApiError as error:
                    reason = error.reason.lower()
                    if reason in _SKIPPABLE_TRACK_REASONS or error.status_code == 404:
                        skipped.append(video_id)
                        continue
                    LOGGER.error(
                        "YouTube track insert failed [%s] reason=%s status=%s message=%s",
                        diagnostic,
                        error.reason,
                        error.status_code,
                        _safe_log_text(error.message),
                    )
                    if not added:
                        _delete_quietly(client, playlist_id)
                    raise _public_error(error, diagnostic) from error

            if not added:
                _delete_quietly(client, playlist_id)
                raise YouTubeAccountError(
                    "YouTube created the playlist container but rejected every track. "
                    f"Reference: {diagnostic}."
                )

            applied_privacy = "PRIVATE"
            privacy_warning = ""
            if privacy_status != "PRIVATE":
                try:
                    _set_privacy(
                        client,
                        playlist_id,
                        normalized_title,
                        normalized_description,
                        privacy_status,
                    )
                    applied_privacy = privacy_status
                except _GoogleApiError as error:
                    privacy_warning = (
                        "The playlist was kept private because YouTube rejected the selected privacy."
                    )
                    LOGGER.warning(
                        "YouTube privacy update failed [%s] reason=%s status=%s message=%s",
                        diagnostic,
                        error.reason,
                        error.status_code,
                        _safe_log_text(error.message),
                    )

    except YouTubeAccountError:
        raise
    except _GoogleApiError as error:
        LOGGER.error(
            "YouTube playlist create failed [%s] reason=%s status=%s message=%s",
            diagnostic,
            error.reason,
            error.status_code,
            _safe_log_text(error.message),
        )
        raise _public_error(error, diagnostic) from error
    except Exception as error:
        LOGGER.exception(
            "Unexpected YouTube publish failure [%s]: %s",
            diagnostic,
            _safe_log_text(error),
        )
        raise YouTubeAccountError(
            "YouTube could not create the playlist. "
            f"Diagnostic reference: {diagnostic}."
        ) from error

    warning_parts: list[str] = []
    if skipped:
        warning_parts.append(
            f"YouTube skipped {len(skipped)} of {len(unique_video_ids)} tracks that could not be added."
        )
    if privacy_warning:
        warning_parts.append(privacy_warning)

    return {
        "playlist_id": playlist_id,
        "title": normalized_title,
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
