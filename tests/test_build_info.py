from __future__ import annotations

from fastapi.testclient import TestClient

from backend.build_info import current_build_info
from backend.application import app


def test_build_info_defaults_to_dev_without_claiming_a_release(monkeypatch) -> None:
    monkeypatch.delenv("PLAYLISTMUSE_VERSION", raising=False)
    monkeypatch.delenv("PLAYLISTMUSE_CHANNEL", raising=False)
    monkeypatch.delenv("PLAYLISTMUSE_GIT_SHA", raising=False)

    info = current_build_info()

    assert info.version == "dev"
    assert info.channel == "dev"
    assert info.commit == ""
    assert info.display == "dev"


def test_build_info_formats_stable_beta_and_dev_builds(monkeypatch) -> None:
    monkeypatch.setenv("PLAYLISTMUSE_VERSION", "0.1.1")
    monkeypatch.setenv("PLAYLISTMUSE_CHANNEL", "stable")
    monkeypatch.delenv("PLAYLISTMUSE_GIT_SHA", raising=False)
    assert current_build_info().display == "v0.1.1 · stable"

    monkeypatch.setenv("PLAYLISTMUSE_VERSION", "0.2.0-beta.1")
    monkeypatch.setenv("PLAYLISTMUSE_CHANNEL", "beta")
    assert current_build_info().display == "v0.2.0-beta.1 · beta"

    monkeypatch.setenv("PLAYLISTMUSE_VERSION", "0.2.0-dev")
    monkeypatch.setenv("PLAYLISTMUSE_CHANNEL", "dev")
    monkeypatch.setenv("PLAYLISTMUSE_GIT_SHA", "472c481f65da13876694f846708e2177981a7a7e")
    info = current_build_info()
    assert info.commit == "472c481"
    assert info.display == "v0.2.0-dev · 472c481"


def test_version_endpoint_reports_running_build_metadata(monkeypatch) -> None:
    monkeypatch.setenv("PLAYLISTMUSE_VERSION", "0.3.0-beta.2")
    monkeypatch.setenv("PLAYLISTMUSE_CHANNEL", "beta")
    monkeypatch.setenv("PLAYLISTMUSE_GIT_SHA", "abcdef1234567890")

    response = TestClient(app).get("/api/version")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "version": "0.3.0-beta.2",
        "channel": "beta",
        "commit": "abcdef1",
        "display": "v0.3.0-beta.2 · beta",
        "repository_url": "https://github.com/steventrux/PlaylistMuse",
    }
