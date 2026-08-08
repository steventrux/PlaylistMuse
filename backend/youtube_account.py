"""YouTube Music OAuth account connection and secure token persistence.

The integration uses ytmusicapi's OAuth device flow. OAuth client credentials,
tokens and pending authorization state are persisted inside PLAYLISTMUSE_DATA_DIR
with restrictive file permissions.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import quote

import httpx
from ytmusicapi import YTMusic

try:  # ytmusicapi exports this in current releases.
    from ytmusicapi import OAuthCredentials
except ImportError:  # Compatibility with releases that only expose the nested path.
    from ytmusicapi.auth.oauth.credentials import OAuthCredentials

from backend.config import DATA_DIR
from backend.storage import delete_file, read_json_object, write_secure_json

YOUTUBE_SETTINGS_PATH = DATA_DIR / "youtube-settings.json"
YOUTUBE_TOKEN_PATH = DATA_DIR / "youtube-oauth.json"
YOUTUBE_PENDING_PATH = DATA_DIR / "youtube-oauth-pending.json"
YOUTUBE_SCOPE = "https://www.googleapis.com/auth/youtube"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
_FATAL_REFRESH_ERRORS = {"invalid_grant", "invalid_token"}


class YouTubeAccountError(ValueError):
    """Public-safe account integration error."""


def load_youtube_settings() -> dict[str, str]:
    values = read_json_object(YOUTUBE_SETTINGS_PATH)
    return {
        "client_id": str(values.get("client_id", "")).strip(),
        "client_secret": str(values.get("client_secret", "")).strip(),
    }


def youtube_settings_response() -> dict[str, Any]:
    settings = load_youtube_settings()
    return {
        "client_id": settings["client_id"],
        "client_secret_set": bool(settings["client_secret"]),
        "configured": bool(settings["client_id"] and settings["client_secret"]),
    }


def save_youtube_settings(client_id: str, client_secret: str = "") -> dict[str, Any]:
    current = load_youtube_settings()
    normalized_client_id = client_id.strip()
    normalized_secret = client_secret.strip() or current["client_secret"]

    if not normalized_client_id:
        raise YouTubeAccountError("Enter the Google OAuth client ID.")
    if not normalized_secret:
        raise YouTubeAccountError("Enter the Google OAuth client secret.")

    changed_client = bool(
        current["client_id"] and current["client_id"] != normalized_client_id
    )
    changed_secret = bool(
        client_secret.strip() and current["client_secret"] != normalized_secret
    )
    write_secure_json(
        YOUTUBE_SETTINGS_PATH,
        {"client_id": normalized_client_id, "client_secret": normalized_secret},
    )

    # Existing tokens can only be refreshed by the OAuth client that created them.
    if changed_client or changed_secret:
        delete_file(YOUTUBE_TOKEN_PATH)
        delete_file(YOUTUBE_PENDING_PATH)

    return youtube_settings_response()


def _oauth_credentials() -> OAuthCredentials:
    settings = load_youtube_settings()
    if not settings["client_id"] or not settings["client_secret"]:
        raise YouTubeAccountError(
            "Configure a Google OAuth client for TVs and Limited Input devices first."
        )
    return OAuthCredentials(
        client_id=settings["client_id"],
        client_secret=settings["client_secret"],
    )


def _ytmusic_client() -> YTMusic:
    if not YOUTUBE_TOKEN_PATH.exists():
        raise YouTubeAccountError("Connect a YouTube Music account first.")
    settings = load_youtube_settings()
    if not settings["client_id"] or not settings["client_secret"]:
        raise YouTubeAccountError("The Google OAuth client configuration is missing.")
    credentials = OAuthCredentials(
        client_id=settings["client_id"],
        client_secret=settings["client_secret"],
    )
    return YTMusic(
        str(YOUTUBE_TOKEN_PATH),
        oauth_credentials=credentials,
    )


def _account_payload(account: dict[str, Any] | None) -> dict[str, Any]:
    values = account if isinstance(account, dict) else {}
    return {
        "account_name": str(values.get("accountName", "")).strip() or None,
        "channel_handle": str(values.get("channelHandle", "")).strip() or None,
        "account_photo_url": str(values.get("accountPhotoUrl", "")).strip() or None,
    }


def _saved_token_is_usable() -> bool:
    token = read_json_object(YOUTUBE_TOKEN_PATH)
    required = (
        "scope",
        "token_type",
        "access_token",
        "refresh_token",
        "expires_at",
        "expires_in",
    )
    return all(token.get(field) not in (None, "") for field in required)


def _access_token_is_current(token: dict[str, Any]) -> bool:
    return bool(
        str(token.get("access_token", "")).strip()
        and int(token.get("expires_at", 0) or 0) > int(time.time()) + 60
    )


def _refresh_token_has_expired(token: dict[str, Any]) -> bool:
    expires_at = int(token.get("refresh_expires_at", 0) or 0)
    return bool(expires_at and expires_at <= int(time.time()) + 60)


def _refresh_failure_requires_reconnect(value: Any) -> bool:
    text = str(value).casefold()
    return any(
        marker in text
        for marker in (
            "invalid_grant",
            "invalid token",
            "invalid_token",
            "token has been expired",
            "token has been revoked",
            "expired or revoked",
        )
    )


def _expired_authorization_error() -> YouTubeAccountError:
    return YouTubeAccountError(
        "The Google authorization expired or was revoked. "
        "Reconnect the YouTube Music account."
    )


def _refresh_access_token_sync() -> str:
    """Refresh and persist the access token, invalidating unusable account tokens."""

    token = read_json_object(YOUTUBE_TOKEN_PATH)
    refresh_token = str(token.get("refresh_token", "")).strip()
    if not refresh_token:
        delete_file(YOUTUBE_TOKEN_PATH)
        raise _expired_authorization_error()
    if _refresh_token_has_expired(token):
        delete_file(YOUTUBE_TOKEN_PATH)
        raise _expired_authorization_error()

    try:
        fresh = _oauth_credentials().refresh_token(refresh_token)
    except Exception as error:
        if _refresh_failure_requires_reconnect(error):
            delete_file(YOUTUBE_TOKEN_PATH)
            raise _expired_authorization_error() from error
        raise YouTubeAccountError(
            "Google could not refresh the authorization. Verify the OAuth client settings "
            "and try again."
        ) from error

    if not isinstance(fresh, dict):
        raise YouTubeAccountError("Google returned an invalid token refresh response.")

    refresh_error = str(fresh.get("error", "")).strip()
    if refresh_error:
        description = str(fresh.get("error_description", "")).strip()
        if refresh_error.casefold() in _FATAL_REFRESH_ERRORS or _refresh_failure_requires_reconnect(
            f"{refresh_error} {description}"
        ):
            delete_file(YOUTUBE_TOKEN_PATH)
            raise _expired_authorization_error()
        raise YouTubeAccountError(description or "Google could not refresh the authorization.")

    access_token = str(fresh.get("access_token", "")).strip()
    if not access_token:
        delete_file(YOUTUBE_TOKEN_PATH)
        raise _expired_authorization_error()

    now = int(time.time())
    access_expires_in = max(1, int(fresh.get("expires_in", 3600)))
    token["access_token"] = access_token
    token["expires_at"] = now + access_expires_in
    token["token_type"] = (
        str(fresh.get("token_type", token.get("token_type", "Bearer"))) or "Bearer"
    )
    if fresh.get("scope"):
        token["scope"] = fresh["scope"]
    if fresh.get("refresh_token"):
        token["refresh_token"] = str(fresh["refresh_token"]).strip()

    raw_refresh_expires_in = fresh.get("refresh_token_expires_in")
    if raw_refresh_expires_in not in (None, ""):
        refresh_expires_in = int(raw_refresh_expires_in)
        if refresh_expires_in > 0:
            token["refresh_expires_at"] = now + refresh_expires_in
            token["expires_in"] = max(access_expires_in, refresh_expires_in)

    write_secure_json(YOUTUBE_TOKEN_PATH, token)
    return access_token


def _optional_account_profile_sync(client: Any | None = None) -> dict[str, Any]:
    """Retrieve account presentation data without deciding connection validity.

    Google returning a refreshable OAuth token is sufficient to consider the account
    connected. Some regular and brand accounts do not expose the account-menu shape
    expected by ytmusicapi, so name, handle and photo are best-effort enrichment only.
    """

    try:
        ytmusic = client or _ytmusic_client()
        account = ytmusic.get_account_info()
    except Exception:
        return {}
    return account if isinstance(account, dict) else {}


def _validate_youtube_connection_sync(client: Any | None = None) -> dict[str, Any]:
    """Backward-compatible alias used by existing deployment checks."""

    return _optional_account_profile_sync(client)


async def youtube_status() -> dict[str, Any]:
    settings = youtube_settings_response()
    response: dict[str, Any] = {
        "catalog_available": True,
        "credentials_configured": settings["configured"],
        "account_connected": False,
        "reconnect_required": False,
        "account_name": None,
        "channel_handle": None,
        "account_photo_url": None,
        "message": "Public YouTube Music catalogue available",
    }

    if not settings["configured"]:
        response["message"] = "Configure the Google OAuth client to connect an account"
        return response
    if not _saved_token_is_usable():
        response["message"] = "Google OAuth client configured · account not connected"
        return response

    token = read_json_object(YOUTUBE_TOKEN_PATH)
    if _refresh_token_has_expired(token):
        delete_file(YOUTUBE_TOKEN_PATH)
        response["reconnect_required"] = True
        response["message"] = str(_expired_authorization_error())
        return response

    if not _access_token_is_current(token):
        try:
            await asyncio.to_thread(_refresh_access_token_sync)
        except YouTubeAccountError as error:
            response["reconnect_required"] = not YOUTUBE_TOKEN_PATH.exists()
            response["message"] = str(error)
            return response

    account = await asyncio.to_thread(_optional_account_profile_sync)
    response.update(_account_payload(account))
    response["account_connected"] = True
    response["message"] = (
        f"Connected as {response['account_name']}"
        if response["account_name"]
        else "YouTube Music account connected"
    )
    return response


def _start_authorization_sync() -> dict[str, Any]:
    try:
        code = _oauth_credentials().get_code()
    except Exception as error:
        raise YouTubeAccountError(
            "Google could not create an authorization code. Verify that the OAuth client "
            "type is TVs and Limited Input devices and that YouTube Data API v3 is enabled."
        ) from error

    required = ("device_code", "user_code", "verification_url", "expires_in", "interval")
    if not all(code.get(name) for name in required):
        raise YouTubeAccountError("Google did not return a valid authorization code.")

    now = int(time.time())
    interval = max(5, int(code.get("interval", 5)))
    pending = {
        "device_code": str(code["device_code"]),
        "user_code": str(code["user_code"]),
        "verification_url": str(code["verification_url"]),
        "expires_at": now + int(code["expires_in"]),
        "interval": interval,
    }
    write_secure_json(YOUTUBE_PENDING_PATH, pending)

    separator = "&" if "?" in pending["verification_url"] else "?"
    complete_url = (
        f"{pending['verification_url']}{separator}user_code="
        f"{quote(pending['user_code'])}"
    )
    return {
        "status": "authorization_required",
        "user_code": pending["user_code"],
        "verification_url": pending["verification_url"],
        "verification_url_complete": complete_url,
        "expires_in": int(code["expires_in"]),
        "interval": interval,
    }


async def start_authorization() -> dict[str, Any]:
    return await asyncio.to_thread(_start_authorization_sync)


def _token_payload(raw_token: dict[str, Any]) -> dict[str, Any]:
    access_token = str(raw_token.get("access_token", "")).strip()
    refresh_token = str(raw_token.get("refresh_token", "")).strip()
    if not access_token or not refresh_token:
        raise YouTubeAccountError("Google did not return a refreshable account token.")

    now = int(time.time())
    access_expires_in = max(1, int(raw_token.get("expires_in", 3600)))
    refresh_expires_in = access_expires_in
    raw_refresh_expires_in = raw_token.get("refresh_token_expires_in")
    if raw_refresh_expires_in not in (None, ""):
        refresh_expires_in = max(access_expires_in, int(raw_refresh_expires_in))

    payload: dict[str, Any] = {
        "scope": str(raw_token.get("scope", YOUTUBE_SCOPE)) or YOUTUBE_SCOPE,
        "token_type": str(raw_token.get("token_type", "Bearer")) or "Bearer",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": now + access_expires_in,
        "expires_in": refresh_expires_in,
    }
    if raw_refresh_expires_in not in (None, "") and int(raw_refresh_expires_in) > 0:
        payload["refresh_expires_at"] = now + int(raw_refresh_expires_in)
    return payload


def _poll_authorization_sync() -> dict[str, Any]:
    pending = read_json_object(YOUTUBE_PENDING_PATH)
    if not pending.get("device_code"):
        return {"status": "idle", "message": "No authorization is in progress."}

    if int(pending.get("expires_at", 0)) <= int(time.time()):
        delete_file(YOUTUBE_PENDING_PATH)
        return {"status": "expired", "message": "The Google authorization code expired."}

    try:
        raw_token = _oauth_credentials().token_from_code(str(pending["device_code"]))
    except Exception as error:
        raise YouTubeAccountError(
            "Google could not verify the authorization. Check the OAuth client credentials "
            "and try connecting again."
        ) from error

    if not isinstance(raw_token, dict):
        raise YouTubeAccountError("Google returned an invalid authorization response.")

    error = str(raw_token.get("error", "")).strip()
    if error == "authorization_pending":
        return {
            "status": "pending",
            "interval": int(pending.get("interval", 5)),
            "message": "Waiting for Google authorization.",
        }
    if error == "slow_down":
        pending["interval"] = int(pending.get("interval", 5)) + 5
        write_secure_json(YOUTUBE_PENDING_PATH, pending)
        return {
            "status": "pending",
            "interval": pending["interval"],
            "message": "Waiting for Google authorization.",
        }
    if error in {"access_denied", "authorization_declined"}:
        delete_file(YOUTUBE_PENDING_PATH)
        return {"status": "denied", "message": "Google authorization was denied."}
    if error in {"expired_token", "invalid_grant"}:
        delete_file(YOUTUBE_PENDING_PATH)
        return {"status": "expired", "message": "The Google authorization code expired."}
    if error:
        description = str(raw_token.get("error_description", "")).strip()
        raise YouTubeAccountError(description or "Google authorization failed.")

    write_secure_json(YOUTUBE_TOKEN_PATH, _token_payload(raw_token))
    delete_file(YOUTUBE_PENDING_PATH)
    account = _optional_account_profile_sync()
    return {
        "status": "connected",
        "account_connected": True,
        **_account_payload(account),
        "message": "YouTube Music account connected.",
    }


async def poll_authorization() -> dict[str, Any]:
    return await asyncio.to_thread(_poll_authorization_sync)


async def disconnect_youtube() -> dict[str, Any]:
    token = read_json_object(YOUTUBE_TOKEN_PATH)
    token_to_revoke = str(
        token.get("refresh_token") or token.get("access_token") or ""
    ).strip()
    if token_to_revoke:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                await client.post(GOOGLE_REVOKE_URL, data={"token": token_to_revoke})
        except Exception:
            # Local disconnect must still succeed if Google is temporarily unreachable.
            pass

    delete_file(YOUTUBE_TOKEN_PATH)
    delete_file(YOUTUBE_PENDING_PATH)
    return {
        "account_connected": False,
        "message": "YouTube Music account disconnected.",
    }
