from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import backend.playlist_library as playlist_library_module
import backend.playlist_tags as playlist_tags_module
from backend.application import app
from backend.playlist_library import PlaylistLibrary
from backend.playlist_tags import normalize_playlist_tags, suggest_playlist_tags

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def sample_playlist() -> dict:
    return {
        "name": "Night drive",
        "description": "Warm guitars after dark.",
        "prompt": "A slow-burning rock night drive from the late 1970s",
        "tracks": [
            {"video_id": "abc123", "title": "Track one", "artists": "Artist one"},
            {"video_id": "def456", "title": "Track two", "artists": "Artist two"},
        ],
    }


def test_tag_normalization_is_bounded_and_case_insensitive() -> None:
    tags = normalize_playlist_tags(
        {
            "genre": [" Rock ", "rock", "Blues Rock", "Hard Rock", "Metal"],
            "mood": ["Energetic", " atmospheric ", "Reflective"],
            "period": ["1970s–1980s", "1990s"],
            "context": ["Road trip"],
        }
    )

    assert tags == {
        "genre": ["Rock", "Blues Rock", "Hard Rock"],
        "mood": ["Energetic", "atmospheric"],
        "period": ["1970s–1980s"],
    }


def test_playlist_tagger_uses_multilingual_library_only_categories(monkeypatch) -> None:
    captured: dict[str, str] = {}

    async def fake_request(config, prompt, *, system_prompt, max_tokens, model):
        captured["prompt"] = prompt
        captured["system_prompt"] = system_prompt
        return (
            '{"genre":["Rock","Blues Rock"],'
            '"mood":["Atmospheric","Reflective"],'
            '"period":["1970s–1980s"]}'
        )

    monkeypatch.setattr(playlist_tags_module, "request_structured_json", fake_request)
    config = SimpleNamespace(configured=True, model_chain=("model-a",))

    tags = asyncio.run(suggest_playlist_tags(config, sample_playlist()))

    assert tags["genre"] == ["Rock", "Blues Rock"]
    assert tags["mood"] == ["Atmospheric", "Reflective"]
    assert tags["period"] == ["1970s–1980s"]
    assert "any language" in captured["system_prompt"]
    assert "short English labels" in captured["system_prompt"]
    assert "Never add categories beyond genre, mood and period" in captured["system_prompt"]
    assert "Night drive" in captured["prompt"]


def test_library_preserves_existing_tags_when_legacy_update_omits_them(tmp_path: Path) -> None:
    library = PlaylistLibrary(tmp_path / "playlists.db")
    playlist = sample_playlist()
    playlist["tags"] = {
        "genre": ["Rock"],
        "mood": ["Atmospheric"],
        "period": ["1970s"],
    }
    created = library.create(playlist)

    legacy_update = sample_playlist()
    updated = library.update(created["id"], legacy_update)

    assert updated["playlist"]["tags"] == playlist["tags"]
    assert library.list()[0]["tags"] == playlist["tags"]


def test_library_api_auto_tags_new_playlist_without_changing_generation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        playlist_library_module,
        "_library",
        PlaylistLibrary(tmp_path / "api-playlists.db"),
    )

    async def fake_suggest(config, playlist):
        return {
            "genre": ["Rock"],
            "mood": ["Atmospheric"],
            "period": ["1970s"],
        }

    monkeypatch.setattr(playlist_library_module, "suggest_playlist_tags", fake_suggest)
    client = TestClient(app)

    created = client.post(
        "/api/library/playlists",
        json={"playlist": sample_playlist(), "generation_request": {"mode": "prompt"}},
    )

    assert created.status_code == 201
    payload = created.json()
    assert payload["playlist"]["tags"] == {
        "genre": ["Rock"],
        "mood": ["Atmospheric"],
        "period": ["1970s"],
    }

    legacy_playlist = sample_playlist()
    updated = client.put(
        f"/api/library/playlists/{payload['id']}",
        json={"playlist": legacy_playlist, "generation_request": {"mode": "prompt"}},
    )
    assert updated.status_code == 200
    assert updated.json()["playlist"]["tags"] == payload["playlist"]["tags"]


def test_library_tag_ui_supports_filters_search_editing_and_ai_suggestion() -> None:
    page = (FRONTEND / "library.html").read_text(encoding="utf-8")
    library_script = (FRONTEND / "library.js").read_text(encoding="utf-8")
    tags_script = (FRONTEND / "library-tags.js").read_text(encoding="utf-8")

    assert 'id="library-genre-filter"' in page
    assert 'id="library-mood-filter"' in page
    assert 'id="library-period-filter"' in page
    assert "/static/library-tags.js?v=1" in page
    assert "tagTools?.searchValues(item)" in library_script
    assert "tagTools?.matchesFilters(item)" in library_script
    assert "tagTools?.refreshFilters(libraryItems)" in library_script
    assert "/tags/suggest" in tags_script
    assert "Save tags" in tags_script
    assert "Suggest with AI" in tags_script
