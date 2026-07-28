from __future__ import annotations

from pathlib import Path

import backend.youtube_account as youtube_account


def _use_temp_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(youtube_account, "DATA_DIR", tmp_path)
    monkeypatch.setattr(youtube_account, "YOUTUBE_SETTINGS_PATH", tmp_path / "youtube-settings.json")
    monkeypatch.setattr(youtube_account, "YOUTUBE_TOKEN_PATH", tmp_path / "youtube-oauth.json")
    monkeypatch.setattr(youtube_account, "YOUTUBE_PENDING_PATH", tmp_path / "youtube-oauth-pending.json")


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
    youtube_account._write_secure_json(
        youtube_account.YOUTUBE_TOKEN_PATH,
        {"access_token": "old", "refresh_token": "old-refresh"},
    )

    youtube_account.save_youtube_settings("client-two", "secret-two")

    assert not youtube_account.YOUTUBE_TOKEN_PATH.exists()


def test_token_payload_contains_only_refreshable_token_fields() -> None:
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
    }
    assert token["expires_in"] == 604800


def test_create_playlist_preserves_order_and_removes_exact_duplicate_ids(monkeypatch) -> None:
    captured = {}

    class FakeYTMusic:
        def create_playlist(self, **kwargs):
            captured.update(kwargs)
            return "PL-test"

    monkeypatch.setattr(youtube_account, "_ytmusic_client", lambda: FakeYTMusic())

    result = youtube_account._create_playlist_sync(
        "Test playlist",
        "Test description",
        "UNLISTED",
        ["video-2", "video-1", "video-2", "video-3"],
    )

    assert captured["video_ids"] == ["video-2", "video-1", "video-3"]
    assert captured["privacy_status"] == "UNLISTED"
    assert result["playlist_id"] == "PL-test"
    assert result["url"].endswith("list=PL-test")
