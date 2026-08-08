from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import backend.youtube_account as youtube_account


def _use_temp_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(youtube_account, "DATA_DIR", tmp_path)
    monkeypatch.setattr(youtube_account, "YOUTUBE_SETTINGS_PATH", tmp_path / "youtube-settings.json")
    monkeypatch.setattr(youtube_account, "YOUTUBE_TOKEN_PATH", tmp_path / "youtube-oauth.json")
    monkeypatch.setattr(youtube_account, "YOUTUBE_PENDING_PATH", tmp_path / "youtube-oauth-pending.json")


def _saved_token(**overrides) -> dict:
    token = {
        "scope": youtube_account.YOUTUBE_SCOPE,
        "token_type": "Bearer",
        "access_token": "old-access",
        "refresh_token": "old-refresh",
        "expires_at": 900,
        "expires_in": 604800,
    }
    token.update(overrides)
    return token


def test_youtube_settings_hide_secret_and_retain_saved_value(monkeypatch, tmp_path: Path) -> None:
    _use_temp_paths(monkeypatch, tmp_path)

    response = youtube_account.save_youtube_settings("client-one", "secret-one")
    assert response == {
        "client_id": "client-one",
        "client_secret_set": True,
        "configured": True,
    }
    assert "secret" not in response

    response = youtube_account.save_youtube_settings("client-one", "")
    assert response["configured"] is True
    assert youtube_account.load_youtube_settings()["client_secret"] == "secret-one"


def test_changing_oauth_client_invalidates_old_token(monkeypatch, tmp_path: Path) -> None:
    _use_temp_paths(monkeypatch, tmp_path)
    youtube_account.save_youtube_settings("client-one", "secret-one")
    youtube_account.write_secure_json(
        youtube_account.YOUTUBE_TOKEN_PATH,
        {"access_token": "old", "refresh_token": "old-refresh"},
    )

    youtube_account.save_youtube_settings("client-two", "secret-two")

    assert not youtube_account.YOUTUBE_TOKEN_PATH.exists()


def test_token_payload_persists_absolute_refresh_expiry(monkeypatch) -> None:
    monkeypatch.setattr(youtube_account.time, "time", lambda: 1_000_000)

    token = youtube_account._token_payload(
        {
            "access_token": "access",
            "refresh_token": "refresh",
            "scope": youtube_account.YOUTUBE_SCOPE,
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token_expires_in": 604800,
            "unexpected": "not persisted",
        }
    )

    assert set(token) == {
        "scope",
        "token_type",
        "access_token",
        "refresh_token",
        "expires_at",
        "expires_in",
        "refresh_expires_at",
    }
    assert token["expires_at"] == 1_003_600
    assert token["expires_in"] == 604800
    assert token["refresh_expires_at"] == 1_604_800


def test_invalid_grant_refresh_invalidates_saved_token(monkeypatch, tmp_path: Path) -> None:
    _use_temp_paths(monkeypatch, tmp_path)
    youtube_account.write_secure_json(youtube_account.YOUTUBE_TOKEN_PATH, _saved_token())

    class Credentials:
        def refresh_token(self, refresh_token: str) -> dict:
            assert refresh_token == "old-refresh"
            return {
                "error": "invalid_grant",
                "error_description": "Token has been expired or revoked.",
            }

    monkeypatch.setattr(youtube_account, "_oauth_credentials", lambda: Credentials())

    with pytest.raises(youtube_account.YouTubeAccountError, match="expired or was revoked"):
        youtube_account._refresh_access_token_sync()

    assert not youtube_account.YOUTUBE_TOKEN_PATH.exists()


def test_status_marks_known_expired_refresh_token_for_reconnect(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _use_temp_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(youtube_account.time, "time", lambda: 1_000_000)
    youtube_account.save_youtube_settings("client-one", "secret-one")
    youtube_account.write_secure_json(
        youtube_account.YOUTUBE_TOKEN_PATH,
        _saved_token(
            access_token="still-present",
            expires_at=1_003_600,
            refresh_expires_at=999_999,
        ),
    )

    status = asyncio.run(youtube_account.youtube_status())

    assert status["account_connected"] is False
    assert status["reconnect_required"] is True
    assert "Reconnect the YouTube Music account" in status["message"]
    assert not youtube_account.YOUTUBE_TOKEN_PATH.exists()


def test_successful_refresh_updates_access_token(monkeypatch, tmp_path: Path) -> None:
    _use_temp_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(youtube_account.time, "time", lambda: 1_000_000)
    youtube_account.write_secure_json(youtube_account.YOUTUBE_TOKEN_PATH, _saved_token())

    class Credentials:
        def refresh_token(self, refresh_token: str) -> dict:
            assert refresh_token == "old-refresh"
            return {
                "access_token": "fresh-access",
                "expires_in": 3600,
                "token_type": "Bearer",
            }

    monkeypatch.setattr(youtube_account, "_oauth_credentials", lambda: Credentials())

    assert youtube_account._refresh_access_token_sync() == "fresh-access"
    saved = youtube_account.read_json_object(youtube_account.YOUTUBE_TOKEN_PATH)
    assert saved["access_token"] == "fresh-access"
    assert saved["refresh_token"] == "old-refresh"
    assert saved["expires_at"] == 1_003_600


def test_legacy_account_publisher_is_not_exposed() -> None:
    assert not hasattr(youtube_account, "create_youtube_playlist")
    assert not hasattr(youtube_account, "_create_playlist_sync")
