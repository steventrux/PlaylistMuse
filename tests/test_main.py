import asyncio
import json

from fastapi.testclient import TestClient

import backend.llm as llm_module
import backend.main as main_module
from backend.config import AppConfig, api_key_slot
from backend.llm import (
    _attempt_count,
    _batch_size,
    _openrouter_max_tokens,
    _playlist_response_format,
)
from backend.youtube import track_identity_key


def test_health() -> None:
    client = TestClient(main_module.app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "application": "PlaylistMuse"}


def test_prompt_analysis_scores_general_semantic_result(monkeypatch) -> None:
    captured: dict = {}

    async def fake_analyze(config, prompt, *, track_count, options):
        captured.update(
            prompt=prompt,
            track_count=track_count,
            options=options,
        )
        return {
            "dimensions": ["genre", "period", "mood_energy", "popularity"],
            "hard_constraints": 3,
            "soft_constraints": 0,
            "structures": ["alternation", "progression"],
            "relations": 2,
            "ambiguities": [],
            "conflicts": [],
            "missing_information": [],
            "imprecisions": [],
            "possible_typos": [],
        }

    monkeypatch.setattr(main_module, "analyze_prompt_semantics", fake_analyze)
    monkeypatch.setattr(main_module, "load_config", lambda: AppConfig())
    client = TestClient(main_module.app)
    response = client.post(
        "/api/prompts/analyze",
        json={
            "prompt": "任意の言語で書かれたプレイリストのリクエスト",
            "track_count": 15,
            "options": {
                "exclude_live": True,
                "exclude_covers": True,
                "exclude_remixes": True,
            },
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "score": 50,
        "level": "Complex",
        "clarity": 100,
        "clarity_level": "Excellent",
        "dimensions": 4,
        "hard_constraints": 3,
        "soft_constraints": 0,
        "structures": 2,
        "relations": 2,
        "issues": [],
    }
    assert captured["prompt"] == "任意の言語で書かれたプレイリストのリクエスト"


def test_prompt_analysis_reports_general_conflicts_and_ambiguities(monkeypatch) -> None:
    async def fake_analyze(config, prompt, *, track_count, options):
        return {
            "dimensions": ["genre"],
            "hard_constraints": 2,
            "soft_constraints": 0,
            "structures": [],
            "relations": 1,
            "ambiguities": ["Define what makes a song beautiful or ugly."],
            "conflicts": ["The two artist requirements cannot both be satisfied."],
            "missing_information": [],
            "imprecisions": [],
            "possible_typos": [],
        }

    monkeypatch.setattr(main_module, "analyze_prompt_semantics", fake_analyze)
    monkeypatch.setattr(main_module, "load_config", lambda: AppConfig())
    response = TestClient(main_module.app).post(
        "/api/prompts/analyze",
        json={"prompt": "A contradictory request", "track_count": 15},
    )

    assert response.status_code == 200
    assert response.json()["clarity"] == 65
    assert response.json()["clarity_level"] == "Fair"
    assert len(response.json()["issues"]) == 2


def test_openrouter_modes_share_one_api_key_slot() -> None:
    assert api_key_slot("openrouter_auto") == "openrouter"
    assert api_key_slot("openrouter_free") == "openrouter"

    config = AppConfig(provider_api_keys={"openrouter": "saved-key"})
    assert config.key_is_saved("openrouter_auto")
    assert config.key_is_saved("openrouter_free")


def test_openrouter_free_enforces_free_router_and_marks_both_modes(monkeypatch) -> None:
    saved: dict[str, AppConfig] = {}

    monkeypatch.setattr(main_module, "load_config", lambda: AppConfig())
    monkeypatch.setattr(
        main_module, "save_config", lambda config: saved.setdefault("config", config)
    )

    client = TestClient(main_module.app)
    response = client.put(
        "/api/settings",
        json={
            "provider": "openrouter_free",
            "api_key": "sk-or-test",
            "model": "paid/model-should-not-be-used",
            "fallback_1": "paid/fallback",
            "fallback_2": "paid/fallback-2",
            "base_url": "https://wrong.example/v1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["model"] == "openrouter/free"
    assert payload["fallback_1"] == ""
    assert payload["fallback_2"] == ""
    assert payload["base_url"] == ""
    assert payload["configured"] is True
    assert payload["provider_keys_set"]["openrouter_auto"] is True
    assert payload["provider_keys_set"]["openrouter_free"] is True
    assert saved["config"].provider_api_keys == {"openrouter": "sk-or-test"}


def test_openrouter_structured_output_schema_and_batch_policy() -> None:
    batch_format = _playlist_response_format(6)
    batch_schema = batch_format["json_schema"]["schema"]
    complete_schema = _playlist_response_format(6, exact_count=True)["json_schema"][
        "schema"
    ]

    assert batch_format["type"] == "json_schema"
    assert batch_format["json_schema"]["strict"] is True
    assert batch_schema["additionalProperties"] is False
    assert batch_schema["properties"]["tracks"]["minItems"] == 1
    assert batch_schema["properties"]["tracks"]["maxItems"] == 6
    assert complete_schema["properties"]["tracks"]["minItems"] == 6
    assert complete_schema["properties"]["tracks"]["maxItems"] == 6
    assert batch_schema["properties"]["tracks"]["items"]["additionalProperties"] is False
    assert _attempt_count("openrouter_free") == 2
    assert _attempt_count("openrouter_auto") == 2
    assert _attempt_count("gemini") == 1
    assert _batch_size("openrouter_free", 25) == 6
    assert _batch_size("openai", 25) == 8
    assert _batch_size("anthropic", 5) == 5
    assert _openrouter_max_tokens(6) >= 4096


def _draft_payload(items: list[tuple[str, str]]) -> str:
    return json.dumps(
        {
            "title": "Complete Playlist",
            "description": "A complete playlist assembled around one coherent idea.",
            "tracks": [
                {
                    "artist": artist,
                    "title": title,
                    "description": f"Description for {title}.",
                    "reason": f"Reason for {title}.",
                }
                for artist, title in items
            ],
        }
    )


def test_complete_request_returns_without_using_batches(monkeypatch) -> None:
    calls: list[tuple[str, int, bool]] = []

    async def fake_request_model(
        client,
        config,
        model,
        user_prompt,
        count,
        *,
        exact_count=False,
    ):
        calls.append((model, count, exact_count))
        return _draft_payload(
            [(f"Artist {index}", f"Track {index}") for index in range(1, count + 1)]
        )

    monkeypatch.setattr(llm_module, "_request_model", fake_request_model)
    config = AppConfig(
        provider="openai",
        api_key="test-key",
        model="primary-model",
    )

    result = asyncio.run(
        llm_module.generate_playlist_draft(config, "A test playlist", 5)
    )

    assert len(result["tracks"]) == 5
    assert calls == [("primary-model", 5, True)]


def test_partial_complete_request_uses_batches_only_for_missing_tracks(monkeypatch) -> None:
    calls: list[tuple[str, int, bool]] = []
    responses = [
        [
            ("Artist A", "Track A"),
            ("Artist B", "Track B"),
        ],
        [
            ("Artist B", "Track B"),
            ("Artist C", "Track C"),
            ("Artist D", "Track D"),
        ],
        [
            ("Artist E", "Track E"),
        ],
    ]

    async def fake_request_model(
        client,
        config,
        model,
        user_prompt,
        count,
        *,
        exact_count=False,
    ):
        calls.append((model, count, exact_count))
        selected = responses[min(len(calls) - 1, len(responses) - 1)]
        return _draft_payload(selected)

    monkeypatch.setattr(llm_module, "_request_model", fake_request_model)
    config = AppConfig(
        provider="openai",
        api_key="test-key",
        model="primary-model",
    )

    result = asyncio.run(
        llm_module.generate_playlist_draft(config, "A test playlist", 5)
    )
    identities = {
        (track["artist"].casefold(), track["title"].casefold())
        for track in result["tracks"]
    }

    assert result["title"] == "Complete Playlist"
    assert len(result["tracks"]) == 5
    assert len(identities) == 5
    assert calls == [
        ("primary-model", 5, True),
        ("primary-model", 3, False),
        ("primary-model", 1, False),
    ]


def test_track_identity_ignores_case_accents_and_punctuation() -> None:
    assert track_identity_key("Bé-Bop-A-Lula!", "Gene Vincent") == track_identity_key(
        "be bop a lula", "GENE VINCENT"
    )


def test_seed_generation_removes_alternate_upload_of_same_song(monkeypatch) -> None:
    async def fake_generate(prompt, count, options):
        return {
            "name": "Fuzz Riffs",
            "description": "Heavy riffs and driving grooves.",
            "prompt": prompt,
            "requested_count": count,
            "resolved_count": 5,
            "tracks": [
                {
                    "video_id": "alternate-upload",
                    "title": "Woman",
                    "artists": "Wolfmother",
                    "album": "Wolfmother",
                    "duration": "2:57",
                    "thumbnail_url": "",
                    "url": "https://music.youtube.com/watch?v=alternate-upload",
                    "description": "A compact blast of fuzz-heavy hard rock.",
                    "reason": "It establishes the playlist's central riff-driven energy.",
                },
                {
                    "video_id": "track-2",
                    "title": "No One Knows",
                    "artists": "Queens of the Stone Age",
                },
                {
                    "video_id": "track-3",
                    "title": "Figure It Out",
                    "artists": "Royal Blood",
                },
                {
                    "video_id": "track-4",
                    "title": "Cochise",
                    "artists": "Audioslave",
                },
                {
                    "video_id": "track-5",
                    "title": "Go With the Flow",
                    "artists": "Queens of the Stone Age",
                },
            ],
            "unresolved": [],
        }

    monkeypatch.setattr(main_module, "_generate", fake_generate)
    client = TestClient(main_module.app)
    response = client.post(
        "/api/playlists/generate-from-seed",
        json={
            "seed": {
                "video_id": "selected-seed",
                "title": "Woman",
                "artists": "Wolfmother",
                "album": "Wolfmother",
                "duration": "2:56",
                "thumbnail_url": "",
                "url": "https://music.youtube.com/watch?v=selected-seed",
            },
            "track_count": 5,
            "options": {
                "exclude_live": True,
                "exclude_covers": True,
                "exclude_remixes": True,
            },
        },
    )

    assert response.status_code == 200
    tracks = response.json()["tracks"]
    identities = [track_identity_key(track["title"], track["artists"]) for track in tracks]
    seed_identity = track_identity_key("Woman", "Wolfmother")

    assert tracks[0]["video_id"] == "selected-seed"
    assert identities.count(seed_identity) == 1
    assert len(identities) == len(set(identities))
