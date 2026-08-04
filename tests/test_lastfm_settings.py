from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import backend.lastfm_settings as lastfm_settings
import backend.main as main_module
import backend.youtube_routes as youtube_routes


def _use_temporary_settings(monkeypatch, tmp_path: Path) -> Path:
    path = tmp_path / "lastfm.json"
    monkeypatch.setattr(lastfm_settings, "LASTFM_SETTINGS_PATH", path)
    monkeypatch.delenv("PLAYLISTMUSE_LASTFM_API_KEY", raising=False)
    return path


def test_lastfm_key_is_stored_securely_and_never_returned(monkeypatch, tmp_path) -> None:
    path = _use_temporary_settings(monkeypatch, tmp_path)
    api_key = "0123456789abcdef0123456789abcdef"

    response = lastfm_settings.save_lastfm_api_key(api_key)

    assert response == {
        "configured": True,
        "api_key_set": True,
        "source": "saved",
    }
    assert api_key not in str(response)
    assert lastfm_settings.lastfm_api_key() == api_key
    assert path.exists()
    assert path.stat().st_mode & 0o777 == 0o600

    disconnected = lastfm_settings.disconnect_lastfm()
    assert disconnected["configured"] is False
    assert not path.exists()


def test_lastfm_settings_routes_control_header_status(monkeypatch, tmp_path) -> None:
    _use_temporary_settings(monkeypatch, tmp_path)

    async def accept_key(api_key: str) -> str:
        return api_key

    monkeypatch.setattr(youtube_routes, "validate_lastfm_api_key", accept_key)
    client = TestClient(main_module.app)

    initial = client.get("/api/lastfm/status")
    assert initial.status_code == 200
    assert initial.json()["configured"] is False

    saved = client.put(
        "/api/lastfm/settings",
        json={"api_key": "abcdef0123456789abcdef0123456789"},
    )
    assert saved.status_code == 200
    assert saved.json() == {
        "configured": True,
        "api_key_set": True,
        "source": "saved",
    }
    assert "abcdef0123456789" not in saved.text

    removed = client.delete("/api/lastfm/settings")
    assert removed.status_code == 200
    assert removed.json()["configured"] is False


def test_invalid_lastfm_key_is_not_saved(monkeypatch, tmp_path) -> None:
    path = _use_temporary_settings(monkeypatch, tmp_path)

    client = TestClient(main_module.app)
    response = client.put(
        "/api/lastfm/settings",
        json={"api_key": "not-a-real-key"},
    )

    assert response.status_code == 400
    assert "32-character" in response.json()["detail"]
    assert not path.exists()


def test_lastfm_rejected_key_is_not_saved(monkeypatch, tmp_path) -> None:
    path = _use_temporary_settings(monkeypatch, tmp_path)

    async def reject_key(_api_key: str) -> str:
        raise ValueError("Last.fm rejected this API key. Check the key and try again.")

    monkeypatch.setattr(youtube_routes, "validate_lastfm_api_key", reject_key)
    client = TestClient(main_module.app)
    response = client.put(
        "/api/lastfm/settings",
        json={"api_key": "abcdef0123456789abcdef0123456789"},
    )

    assert response.status_code == 400
    assert "rejected" in response.json()["detail"]
    assert not path.exists()


def test_environment_key_remains_active_after_saved_key_is_removed(
    monkeypatch,
    tmp_path,
) -> None:
    _use_temporary_settings(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "PLAYLISTMUSE_LASTFM_API_KEY",
        "environment-key-0123456789",
    )
    lastfm_settings.save_lastfm_api_key("fedcba9876543210fedcba9876543210")

    response = lastfm_settings.disconnect_lastfm()

    assert response == {
        "configured": True,
        "api_key_set": True,
        "source": "environment",
    }
    assert lastfm_settings.lastfm_api_key() == "environment-key-0123456789"
