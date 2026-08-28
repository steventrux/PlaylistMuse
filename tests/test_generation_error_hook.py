from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import backend.generation_errors as generation_errors
import backend.main as main_module
from backend.metadata_runtime import MetadataServiceUnavailableError


class _FakeConfig:
    provider = "gemini"
    stats_key = "gemini"


def test_generate_route_records_a_value_error(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "generation_errors.json"
    monkeypatch.setattr(generation_errors, "GENERATION_ERRORS_PATH", path)
    monkeypatch.setattr(main_module, "load_config", lambda: _FakeConfig())

    async def failing_generate(prompt, count, options):
        raise ValueError("Describe the playlist you want.")

    monkeypatch.setattr(main_module, "_generate", failing_generate)

    response = TestClient(main_module.app).post(
        "/api/playlists/generate",
        json={"prompt": "anything", "track_count": 10, "options": {}},
    )

    assert response.status_code == 400
    assert generation_errors.error_breakdown() == {"gemini": {"ValueError": 1}}


def test_generate_route_records_an_unexpected_error(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "generation_errors.json"
    monkeypatch.setattr(generation_errors, "GENERATION_ERRORS_PATH", path)
    monkeypatch.setattr(main_module, "load_config", lambda: _FakeConfig())

    async def failing_generate(prompt, count, options):
        raise RuntimeError("the AI provider timed out")

    monkeypatch.setattr(main_module, "_generate", failing_generate)

    response = TestClient(main_module.app).post(
        "/api/playlists/generate",
        json={"prompt": "anything", "track_count": 10, "options": {}},
    )

    assert response.status_code == 502
    assert generation_errors.error_breakdown() == {"gemini": {"RuntimeError": 1}}


def test_generate_route_surfaces_metadata_outage_detail(
    monkeypatch, tmp_path: Path
) -> None:
    """A MusicBrainz outage must not be flattened into the generic 502 message --
    the caller needs to know it's an external, temporary metadata-service issue,
    not that generation itself is broken."""
    path = tmp_path / "generation_errors.json"
    monkeypatch.setattr(generation_errors, "GENERATION_ERRORS_PATH", path)
    monkeypatch.setattr(main_module, "load_config", lambda: _FakeConfig())

    async def failing_generate(prompt, count, options):
        raise MetadataServiceUnavailableError(
            "MusicBrainz metadata verification is temporarily unavailable."
        )

    monkeypatch.setattr(main_module, "_generate", failing_generate)

    response = TestClient(main_module.app).post(
        "/api/playlists/generate",
        json={"prompt": "anything", "track_count": 10, "options": {}},
    )

    assert response.status_code == 502
    assert "MusicBrainz" in response.json()["detail"]
    assert response.json()["detail"] != "Playlist generation failed. Please try again."
    assert generation_errors.error_breakdown() == {
        "gemini": {"MetadataServiceUnavailableError": 1}
    }


def test_generate_from_seed_route_surfaces_metadata_outage_detail(
    monkeypatch, tmp_path: Path
) -> None:
    path = tmp_path / "generation_errors.json"
    monkeypatch.setattr(generation_errors, "GENERATION_ERRORS_PATH", path)
    monkeypatch.setattr(main_module, "load_config", lambda: _FakeConfig())

    async def failing_generate_from_seed(request):
        raise MetadataServiceUnavailableError(
            "MusicBrainz metadata verification is temporarily unavailable."
        )

    monkeypatch.setattr(
        main_module, "_generate_from_seed_playlist", failing_generate_from_seed
    )

    response = TestClient(main_module.app).post(
        "/api/playlists/generate-from-seed",
        json={
            "seed": {
                "video_id": "seed-1",
                "title": "Seed Track",
                "artists": "Seed Artist",
            },
            "track_count": 10,
        },
    )

    assert response.status_code == 502
    assert "MusicBrainz" in response.json()["detail"]
    assert response.json()["detail"] != "Playlist generation failed. Please try again."


def test_replace_track_route_surfaces_metadata_outage_detail(monkeypatch) -> None:
    async def fake_draft(config, prompt, count):
        return {
            "tracks": [
                {"artist": f"Artist {i}", "title": f"Track {i}"} for i in range(count)
            ]
        }

    async def failing_resolve(candidates, exclusions):
        raise MetadataServiceUnavailableError(
            "MusicBrainz metadata verification is temporarily unavailable."
        )

    monkeypatch.setattr(main_module, "generate_playlist_draft", fake_draft)
    monkeypatch.setattr(main_module, "resolve_candidates", failing_resolve)

    response = TestClient(main_module.app).post(
        "/api/playlists/replace-track",
        json={
            "prompt": "A rock playlist",
            "current_track": {"title": "Old Song", "artists": "Old Artist"},
            "existing_tracks": [],
        },
    )

    assert response.status_code == 502
    assert "MusicBrainz" in response.json()["detail"]
    assert response.json()["detail"] != "Track replacement failed. Please try again."
