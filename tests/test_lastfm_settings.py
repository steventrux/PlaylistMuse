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
    environment_key = "00112233445566778899aabbccddeeff"
    monkeypatch.setenv("PLAYLISTMUSE_LASTFM_API_KEY", environment_key)
    lastfm_settings.save_lastfm_api_key("fedcba9876543210fedcba9876543210")

    response = lastfm_settings.disconnect_lastfm()

    assert response == {
        "configured": True,
        "api_key_set": True,
        "source": "environment",
    }
    assert lastfm_settings.lastfm_api_key() == environment_key


def test_malformed_environment_key_is_not_locally_configured(
    monkeypatch,
    tmp_path,
) -> None:
    _use_temporary_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("PLAYLISTMUSE_LASTFM_API_KEY", "not-a-valid-key")

    assert lastfm_settings.lastfm_settings_response() == {
        "configured": False,
        "api_key_set": False,
        "source": "",
    }
    assert lastfm_settings.lastfm_api_key() == ""


def test_valid_environment_key_is_verified_by_status_route(
    monkeypatch,
    tmp_path,
) -> None:
    _use_temporary_settings(monkeypatch, tmp_path)
    environment_key = "00112233445566778899aabbccddeeff"
    monkeypatch.setenv("PLAYLISTMUSE_LASTFM_API_KEY", environment_key)

    async def accept_key(api_key: str) -> str:
        assert api_key == environment_key
        return api_key

    monkeypatch.setattr(lastfm_settings, "validate_lastfm_api_key", accept_key)
    response = TestClient(main_module.app).get("/api/lastfm/status")

    assert response.status_code == 200
    assert response.json() == {
        "configured": True,
        "api_key_set": True,
        "source": "environment",
        "validation_status": "valid",
    }


def test_rejected_environment_key_is_not_reported_as_configured(
    monkeypatch,
    tmp_path,
) -> None:
    _use_temporary_settings(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "PLAYLISTMUSE_LASTFM_API_KEY",
        "00112233445566778899aabbccddeeff",
    )

    async def reject_key(_api_key: str) -> str:
        raise ValueError("Last.fm rejected this API key.")

    monkeypatch.setattr(lastfm_settings, "validate_lastfm_api_key", reject_key)
    response = TestClient(main_module.app).get("/api/lastfm/settings")

    assert response.status_code == 200
    assert response.json() == {
        "configured": False,
        "api_key_set": True,
        "source": "environment",
        "validation_status": "invalid",
    }


def test_environment_validation_outage_is_reported_as_unavailable(
    monkeypatch,
    tmp_path,
) -> None:
    _use_temporary_settings(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "PLAYLISTMUSE_LASTFM_API_KEY",
        "00112233445566778899aabbccddeeff",
    )

    async def unavailable(_api_key: str) -> str:
        raise RuntimeError("temporary network failure")

    monkeypatch.setattr(lastfm_settings, "validate_lastfm_api_key", unavailable)
    response = TestClient(main_module.app).get("/api/lastfm/status")

    assert response.status_code == 200
    assert response.json() == {
        "configured": False,
        "api_key_set": True,
        "source": "environment",
        "validation_status": "unavailable",
    }
