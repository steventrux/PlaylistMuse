from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
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
            "custom": ["Road trip", "road trip", "Favorites"],
            "context": ["Ignored context"],
        }
    )

    assert tags == {
        "genre": ["Rock", "Blues Rock", "Hard Rock"],
        "mood": ["Energetic", "atmospheric"],
        "period": ["1970s–1980s"],
        "custom": ["Road trip", "Favorites"],
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

    playlist = sample_playlist()
    playlist["tags"] = {"custom": ["My favorite"]}
    tags = asyncio.run(suggest_playlist_tags(config, playlist))

    assert tags["genre"] == ["Rock", "Blues Rock"]
    assert tags["mood"] == ["Atmospheric", "Reflective"]
    assert tags["period"] == ["1970s–1980s"]
    assert tags["custom"] == ["My favorite"]
    assert "any language" in captured["system_prompt"]
    assert "short English labels" in captured["system_prompt"]
    assert "Never add categories beyond genre, mood and period" in captured["system_prompt"]
    assert "Night drive" in captured["prompt"]


def test_playlist_tagger_retries_fallback_after_empty_classification(monkeypatch) -> None:
    models: list[str] = []

    async def fake_request(config, prompt, *, system_prompt, max_tokens, model):
        models.append(model)
        if model == "model-a":
            return '{"genre":[],"mood":[],"period":[]}'
        return (
            '{"genre":["Electronic Pop"],'
            '"mood":["Energetic"],'
            '"period":["2020s"]}'
        )

    monkeypatch.setattr(playlist_tags_module, "request_structured_json", fake_request)
    config = SimpleNamespace(
        configured=True,
        model_chain=("model-a", "model-b"),
    )

    tags = asyncio.run(suggest_playlist_tags(config, sample_playlist()))

    assert models == ["model-a", "model-b"]
    assert tags == {
        "genre": ["Electronic Pop"],
        "mood": ["Energetic"],
        "period": ["2020s"],
        "custom": [],
    }


def test_playlist_tagger_rejects_empty_classification_from_all_models(
    monkeypatch,
) -> None:
    async def fake_request(config, prompt, *, system_prompt, max_tokens, model):
        return '{"genre":[],"mood":[],"period":[]}'

    monkeypatch.setattr(playlist_tags_module, "request_structured_json", fake_request)
    config = SimpleNamespace(
        configured=True,
        model_chain=("model-a", "model-b"),
    )

    with pytest.raises(ValueError, match="no valid playlist tags"):
        asyncio.run(suggest_playlist_tags(config, sample_playlist()))


def test_library_preserves_existing_tags_when_legacy_update_omits_them(tmp_path: Path) -> None:
    library = PlaylistLibrary(tmp_path / "playlists.db")
    playlist = sample_playlist()
    playlist["tags"] = {
        "genre": ["Rock"],
        "mood": ["Atmospheric"],
        "period": ["1970s"],
        "custom": ["Favorites"],
    }
    created = library.create(playlist)

    legacy_update = sample_playlist()
    updated = library.update(created["id"], legacy_update)

    assert updated["playlist"]["tags"] == playlist["tags"]
    assert library.list()[0]["tags"] == playlist["tags"]


@pytest.mark.parametrize("mode", ["prompt", "seed"])
def test_library_api_auto_tags_new_playlist_without_changing_generation(
    monkeypatch,
    tmp_path: Path,
    mode: str,
) -> None:
    monkeypatch.setattr(
        playlist_library_module,
        "_library",
        PlaylistLibrary(tmp_path / f"api-playlists-{mode}.db"),
    )

    async def fake_suggest(config, playlist):
        return {
            "genre": ["Rock"],
            "mood": ["Atmospheric"],
            "period": ["1970s"],
            "custom": [],
        }

    monkeypatch.setattr(playlist_library_module, "suggest_playlist_tags", fake_suggest)
    client = TestClient(app)

    created = client.post(
        "/api/library/playlists",
        json={"playlist": sample_playlist(), "generation_request": {"mode": mode}},
    )

    assert created.status_code == 201
    payload = created.json()
    assert payload["playlist"]["tags"] == {
        "genre": ["Rock"],
        "mood": ["Atmospheric"],
        "period": ["1970s"],
        "custom": [],
    }

    legacy_playlist = sample_playlist()
    updated = client.put(
        f"/api/library/playlists/{payload['id']}",
        json={"playlist": legacy_playlist, "generation_request": {"mode": mode}},
    )
    assert updated.status_code == 200
    assert updated.json()["playlist"]["tags"] == payload["playlist"]["tags"]


def test_library_tag_ui_uses_general_search_click_filters_and_personal_tags() -> None:
    page = (FRONTEND / "library.html").read_text(encoding="utf-8")
    library_script = (FRONTEND / "library.js").read_text(encoding="utf-8")
    tags_script = (FRONTEND / "library-tags.js").read_text(encoding="utf-8")
    tags_style = (FRONTEND / "library-tags.css").read_text(encoding="utf-8")

    assert 'id="library-genre-filter"' not in page
    assert 'id="library-mood-filter"' not in page
    assert 'id="library-period-filter"' not in page
    assert "/static/library-tags.css?v=3" in page
    assert "/static/library-tags.js?v=3" in page
    assert "tagTools?.searchValues(item)" in library_script
    assert "tagTools?.matchesFilters(item)" in library_script
    assert "const activeTagFilters = new Set();" in tags_script
    assert "element.setAttribute('aria-pressed', String(active));" in tags_script
    assert "library-tag-add" in tags_script
    assert "library-tag-delete" in tags_script
    assert "custom: valuesFor(tags, 'custom')" in tags_script
    assert "method: 'PUT'" in tags_script
    assert "/tags/suggest" not in tags_script
    assert "Save tags" not in tags_script
    assert "Suggest with AI" not in tags_script
    assert "Genre up to 3" not in tags_script
    assert ".library-tag-chip.active" in tags_style
    assert ".library-personal-tag" in tags_style


def test_playlist_page_shows_ai_and_personal_tags_with_shared_controls() -> None:
    page = (FRONTEND / "playlist.html").read_text(encoding="utf-8")
    script = (FRONTEND / "playlist.js").read_text(encoding="utf-8")
    tags_script = (FRONTEND / "library-tags.js").read_text(encoding="utf-8")

    assert 'id="playlist-tags"' in page
    assert 'id="playlist-tags-status"' in page
    assert "/static/library-tags.css?v=3" in page
    assert "/static/library-tags.js?v=3" in page
    assert "/static/playlist.js?v=20" in page
    assert "const tagTools = window.PlaylistMuseTags" in script
    assert "function renderPlaylistTags()" in script
    assert "tagTools.editableSummary(data?.tags" in script
    assert "tagTools.addPersonal(data?.tags, value)" in script
    assert "tagTools.removePersonal(data?.tags, value)" in script
    assert "data.tags = record.playlist.tags;" in script
    assert "void refreshPlaylistTagsFromLibrary();" in script
    assert "window.PlaylistMuseTags = api;" in tags_script


def test_tag_add_control_matches_chip_height_and_empty_submit_closes_silently() -> None:
    tags_script = (FRONTEND / "library-tags.js").read_text(encoding="utf-8")
    tags_style = (FRONTEND / "library-tags.css").read_text(encoding="utf-8")

    assert "--playlist-tag-height: 22px;" in tags_style
    assert "height: var(--playlist-tag-height);" in tags_style
    assert "width: var(--playlist-tag-height);" in tags_style
    assert "const label = clean(input.value);" in tags_script
    assert "if (!label) {\n        close();\n        return;\n      }" in tags_script
    assert "form.addEventListener('focusout'" in tags_script
