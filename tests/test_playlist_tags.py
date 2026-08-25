from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import backend.playlist_library as playlist_library_module
import backend.playlist_tags as playlist_tags_module
from backend.application import app
from backend.playlist_library import PlaylistLibrary
from backend.playlist_tags import normalize_playlist_tags, suggest_playlist_tags
from backend.provider_rate_limits import ProviderRateLimitedError

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


def test_playlist_tagger_samples_long_playlists_across_full_sequence() -> None:
    playlist = sample_playlist()
    playlist["tracks"] = [
        {
            "video_id": f"video-{index:03d}",
            "title": f"Track {index:03d}",
            "artists": f"Artist {index:03d}",
        }
        for index in range(100)
    ]

    payload = json.loads(playlist_tags_module._classification_request(playlist))
    sampled_indices = [
        int(line.rsplit("Track ", 1)[1])
        for line in payload["tracks"]
    ]

    assert len(sampled_indices) == playlist_tags_module.MAX_TAGGING_TRACKS
    assert len(set(sampled_indices)) == playlist_tags_module.MAX_TAGGING_TRACKS
    assert sampled_indices[0] == 0
    assert sampled_indices[-1] == 99
    assert max(sampled_indices) > 59
    assert sampled_indices != list(range(playlist_tags_module.MAX_TAGGING_TRACKS))


def test_playlist_tagger_uses_all_tracks_when_within_limit() -> None:
    playlist = sample_playlist()
    playlist["tracks"] = [
        {
            "video_id": f"video-{index:03d}",
            "title": f"Track {index:03d}",
            "artists": f"Artist {index:03d}",
        }
        for index in range(playlist_tags_module.MAX_TAGGING_TRACKS)
    ]

    payload = json.loads(playlist_tags_module._classification_request(playlist))

    assert len(payload["tracks"]) == playlist_tags_module.MAX_TAGGING_TRACKS
    assert "Track 000" in payload["tracks"][0]
    assert "Track 059" in payload["tracks"][-1]


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


def test_playlist_tagger_falls_back_when_a_model_is_rate_limited(monkeypatch) -> None:
    """A model cached as rate-limited must be skipped, not abort the whole fallback loop.

    Regression test: ProviderRateLimitedError used to propagate uncaught out of this
    loop, so a rate-limited primary model failed tagging entirely instead of trying
    the next configured model.
    """
    models: list[str] = []

    async def fake_request(config, prompt, *, system_prompt, max_tokens, model):
        models.append(model)
        if model == "model-a":
            raise ProviderRateLimitedError("openai/model-a is cached as rate-limited")
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


def test_playlist_tagger_rejects_empty_classification_from_all_models(monkeypatch) -> None:
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
    # Tag suggestion now runs in a background task after the response is sent
    # (see test_create_playlist_endpoint_does_not_block_on_tag_suggestion for why:
    # a synchronous await here made saves take 40-50s under provider fallback
    # pressure), so the create response itself carries only the default empty tags.
    assert payload["playlist"]["tags"] == {
        "genre": [], "mood": [], "period": [], "custom": [],
    }

    expected_tags = {
        "genre": ["Rock"],
        "mood": ["Atmospheric"],
        "period": ["1970s"],
        "custom": [],
    }
    library = playlist_library_module.get_library()
    for _ in range(50):
        if library.get(payload["id"])["playlist"]["tags"] == expected_tags:
            break
        time.sleep(0.02)
    else:
        pytest.fail("Background tag suggestion never applied to the stored playlist")

    legacy_playlist = sample_playlist()
    updated = client.put(
        f"/api/library/playlists/{payload['id']}",
        json={"playlist": legacy_playlist, "generation_request": {"mode": mode}},
    )
    assert updated.status_code == 200
    assert updated.json()["playlist"]["tags"] == expected_tags


def test_create_playlist_endpoint_does_not_block_on_tag_suggestion(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """A real production incident: automatic tag suggestion went through a slow AI
    fallback chain (40-50s) while the create endpoint awaited it directly, so the
    save appeared hung and the user reloaded the page repeatedly, each reload
    creating a brand-new duplicate playlist (11 in one session). The create
    response must return as soon as the playlist row exists, with tag suggestion
    applied afterward via a background task instead of blocking the request.
    """
    from fastapi import BackgroundTasks

    monkeypatch.setattr(
        playlist_library_module,
        "_library",
        PlaylistLibrary(tmp_path / "no-block.db"),
    )

    suggestion_called = False

    async def slow_suggest(config, playlist):
        nonlocal suggestion_called
        suggestion_called = True
        return {"genre": ["Rock"], "mood": [], "period": [], "custom": []}

    monkeypatch.setattr(playlist_library_module, "suggest_playlist_tags", slow_suggest)

    request = playlist_library_module.PlaylistWriteRequest(
        playlist=sample_playlist(), generation_request={"mode": "prompt"}
    )
    background_tasks = BackgroundTasks()

    created = asyncio.run(
        playlist_library_module.create_playlist(request, background_tasks)
    )

    assert not suggestion_called, (
        "create_playlist returned before the background tag suggestion ran"
    )
    assert created["playlist"]["tags"] == {
        "genre": [], "mood": [], "period": [], "custom": [],
    }

    asyncio.run(background_tasks())

    assert suggestion_called
    stored = playlist_library_module.get_library().get(created["id"])
    assert stored["playlist"]["tags"]["genre"] == ["Rock"]


def test_library_tag_ui_is_read_only_but_keeps_search_filters() -> None:
    page = (FRONTEND / "library.html").read_text(encoding="utf-8")
    library_script = (FRONTEND / "library.js").read_text(encoding="utf-8")
    tags_script = (FRONTEND / "library-tags.js").read_text(encoding="utf-8")
    tags_style = (FRONTEND / "library-tags.css").read_text(encoding="utf-8")

    assert 'id="library-genre-filter"' not in page
    assert 'id="library-mood-filter"' not in page
    assert 'id="library-period-filter"' not in page
    assert "/static/library-tags.css?v=3" in page
    assert "/static/library-tags.js?v=5" in page
    assert "tagTools?.searchValues(item)" in library_script
    assert "tagTools?.matchesFilters(item)" in library_script
    assert "const activeTagFilters = new Set();" in tags_script
    assert "element.setAttribute('aria-pressed', String(active));" in tags_script
    assert "function summary(item)" in tags_script
    assert "return renderTags(item?.tags, {filterable: true});" in tags_script
    assert "async function updatePersonalTags" not in tags_script
    assert "method: 'PUT'" not in tags_script
    assert "function install(" not in tags_script
    assert "custom: valuesFor(tags, 'custom')" in tags_script
    assert ".library-tag-chip.active" in tags_style


def test_library_tag_filter_expands_combined_period_ranges() -> None:
    # A playlist stored with a combined range like "1970s-1980s" as its one
    # period tag must still match a filter for "1970s" or "1980s" alone --
    # those are exactly the labels Statistics links to, since it splits
    # combined ranges into separate buckets (see backend/playlist_stats.py's
    # _expand_period). Without this, clicking a period in Statistics silently
    # filtered out every playlist tagged with a combined range.
    #
    # Regression: expandPeriod() must not *replace* the combined value with its
    # split decades -- searchValues() keeps the original "1970s-1980s" too, or
    # clicking that exact chip on the card (not via Statistics) matches nothing.
    tags_script = (FRONTEND / "library-tags.js").read_text(encoding="utf-8")

    assert "function expandPeriod(value)" in tags_script
    assert "return expanded.length > 1 ? [period, ...expanded] : expanded;" in tags_script


def test_library_active_filters_are_listed_with_a_clear_action() -> None:
    library_script = (FRONTEND / "library.js").read_text(encoding="utf-8")
    tags_script = (FRONTEND / "library-tags.js").read_text(encoding="utf-8")

    assert "function activeFilters()" in tags_script
    assert "function clearFilter(key)" in tags_script
    assert "tagTools?.activeFilters()" in library_script
    assert "tagTools.clearFilter(key)" in library_script
    assert "Filtered by artist:" in library_script
    assert "Filtered by tag:" in library_script
    assert "Filtered by song:" in library_script
    assert "function clearTrackFilter()" in library_script
    assert "params.set('video_id', trackFilter);" in library_script


def test_active_filters_of_the_same_type_share_one_label() -> None:
    # Multiple active tag filters must render under a single "Filtered by tag:"
    # label with one removable chip per value, not one repeated label per tag.
    library_script = (FRONTEND / "library.js").read_text(encoding="utf-8")

    assert "function filterGroup(labelText, chips)" in library_script
    assert "hint.append(filterGroup('Filtered by tag:', tagFilters.map(" in library_script
    assert "function filterRemoveIcon()" in library_script


def test_playlist_page_shows_ai_and_personal_tags_with_shared_controls() -> None:
    page = (FRONTEND / "playlist.html").read_text(encoding="utf-8")
    script = (FRONTEND / "playlist.js").read_text(encoding="utf-8")
    tags_script = (FRONTEND / "library-tags.js").read_text(encoding="utf-8")

    assert 'id="playlist-tags"' in page
    assert 'id="playlist-tags-status"' in page
    assert "/static/library-tags.css?v=3" in page
    assert "/static/library-tags.js?v=5" in page
    assert "/static/playlist.js?v=26" in page
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
