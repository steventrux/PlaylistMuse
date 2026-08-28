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


def test_favicon_route_uses_current_logo() -> None:
    client = TestClient(main_module.app)
    response = client.get("/favicon.ico")
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-store"
    assert response.headers.get("content-type", "").startswith("image/png")
    assert response.content == (main_module.FRONTEND / "playlistmuse-favicon.png").read_bytes()


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
        "performance_notes": [],
    }
    assert captured["prompt"] == "任意の言語で書かれたプレイリストのリクエスト"


def _empty_semantics() -> dict:
    return {
        "dimensions": [],
        "hard_constraints": 0,
        "soft_constraints": 0,
        "structures": [],
        "relations": 0,
        "ambiguities": [],
        "conflicts": [],
        "missing_information": [],
        "imprecisions": [],
        "possible_typos": [],
    }


def test_prompt_complexity_reflects_the_temporal_range_validation_cost(monkeypatch) -> None:
    """A closed release-year range is known to double MusicBrainz calls per candidate."""

    async def fake_analyze(config, prompt, *, track_count, options):
        return _empty_semantics()

    monkeypatch.setattr(main_module, "analyze_prompt_semantics", fake_analyze)
    monkeypatch.setattr(main_module, "load_config", lambda: AppConfig())
    client = TestClient(main_module.app)

    baseline = client.post(
        "/api/prompts/analyze",
        json={"prompt": "Heavy guitars playlist", "track_count": 15},
    ).json()
    ranged = client.post(
        "/api/prompts/analyze",
        json={
            "prompt": "Heavy guitars playlist between 1990 and 2005",
            "track_count": 15,
        },
    ).json()

    assert baseline["performance_notes"] == []
    assert ranged["score"] > baseline["score"]
    assert ranged["performance_notes"]
    assert "second catalogue lookup" in ranged["performance_notes"][0]


def test_prompt_complexity_reflects_the_artist_country_validation_cost(monkeypatch) -> None:
    async def fake_analyze(config, prompt, *, track_count, options):
        return _empty_semantics()

    monkeypatch.setattr(main_module, "analyze_prompt_semantics", fake_analyze)
    monkeypatch.setattr(main_module, "load_config", lambda: AppConfig())
    client = TestClient(main_module.app)

    baseline = client.post(
        "/api/prompts/analyze",
        json={"prompt": "Party playlist", "track_count": 15},
    ).json()
    with_country = client.post(
        "/api/prompts/analyze",
        json={"prompt": "Crea una playlist di musica italiana per una festa.", "track_count": 15},
    ).json()

    assert with_country["score"] > baseline["score"]
    assert any("Artist-origin" in note for note in with_country["performance_notes"])


def test_prompt_complexity_reflects_the_energy_ordering_validation_cost(monkeypatch) -> None:
    async def fake_analyze(config, prompt, *, track_count, options):
        return _empty_semantics()

    monkeypatch.setattr(main_module, "analyze_prompt_semantics", fake_analyze)
    monkeypatch.setattr(main_module, "load_config", lambda: AppConfig())
    client = TestClient(main_module.app)

    baseline = client.post(
        "/api/prompts/analyze",
        json={"prompt": "Party playlist", "track_count": 15},
    ).json()
    with_energy = client.post(
        "/api/prompts/analyze",
        json={"prompt": "Rock playlist with increasing energy", "track_count": 15},
    ).json()

    assert with_energy["score"] > baseline["score"]
    assert any("Sonic-energy ordering" in note for note in with_energy["performance_notes"])


def test_prompt_complexity_energy_ordering_scales_with_track_count(monkeypatch) -> None:
    async def fake_analyze(config, prompt, *, track_count, options):
        return _empty_semantics()

    monkeypatch.setattr(main_module, "analyze_prompt_semantics", fake_analyze)
    monkeypatch.setattr(main_module, "load_config", lambda: AppConfig())
    client = TestClient(main_module.app)

    small = client.post(
        "/api/prompts/analyze",
        json={"prompt": "Rock playlist with increasing energy", "track_count": 10},
    ).json()
    medium = client.post(
        "/api/prompts/analyze",
        json={"prompt": "Rock playlist with increasing energy", "track_count": 25},
    ).json()
    large = client.post(
        "/api/prompts/analyze",
        json={"prompt": "Rock playlist with increasing energy", "track_count": 60},
    ).json()

    # This mirrors the real measured cost: ~20-25 tracks (the spike's reference case)
    # lands exactly at "Very complex", matching the explicit product requirement that a
    # request costing roughly double the normal generation time reads as very high
    # complexity. Smaller/larger requests scale proportionally with the real added cost.
    assert small["level"] == "Detailed"
    assert medium["level"] == "Very complex"
    assert large["level"] == "Extreme"


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
            "fallback_3": "paid/fallback-3",
            "base_url": "https://wrong.example/v1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["model"] == "openrouter/free"
    assert payload["fallback_1"] == ""
    assert payload["fallback_2"] == ""
    assert payload["fallback_3"] == ""
    assert payload["fallback_8"] == ""
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


def _seed_request(**overrides) -> dict:
    payload = {
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
    }
    payload.update(overrides)
    return payload


def _seed_track_payload(video_id: str, title: str, artists: str) -> dict:
    return {
        "video_id": video_id,
        "title": title,
        "artists": artists,
        "album": "Album",
        "duration": "3:00",
        "thumbnail_url": "",
        "url": f"https://music.youtube.com/watch?v={video_id}",
        "description": "d",
        "reason": "r",
    }


def _seed_draft(prompt: str, count: int, tracks: list[dict]) -> dict:
    return {
        "name": "Fuzz Riffs",
        "description": "Heavy riffs and driving grooves.",
        "prompt": prompt,
        "requested_count": count,
        "resolved_count": len(tracks),
        "tracks": tracks,
        "unresolved": [],
    }


def test_seed_generation_removes_alternate_upload_of_same_song(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_generate(prompt, count, options, *, allow_shortfall=False):
        calls.append(prompt)
        assert count == 4
        if len(calls) == 1:
            # The AI independently reproduces the seed (a different video_id, same
            # identity) among its own suggestions -- this must trigger exactly one retry.
            tracks = [
                _seed_track_payload("alternate-upload", "Woman", "Wolfmother"),
                _seed_track_payload("track-2", "No One Knows", "Queens of the Stone Age"),
                _seed_track_payload("track-3", "Figure It Out", "Royal Blood"),
                _seed_track_payload("track-4", "Cochise", "Audioslave"),
            ]
        else:
            assert "Do not include" in prompt
            tracks = [
                _seed_track_payload("track-2", "No One Knows", "Queens of the Stone Age"),
                _seed_track_payload("track-3", "Figure It Out", "Royal Blood"),
                _seed_track_payload("track-4", "Cochise", "Audioslave"),
                _seed_track_payload("track-5", "Go With the Flow", "Queens of the Stone Age"),
            ]
        return _seed_draft(prompt, count, tracks)

    monkeypatch.setattr(main_module, "_generate", fake_generate)
    client = TestClient(main_module.app)
    response = client.post("/api/playlists/generate-from-seed", json=_seed_request())

    assert response.status_code == 200
    tracks = response.json()["tracks"]
    identities = [track_identity_key(track["title"], track["artists"]) for track in tracks]
    seed_identity = track_identity_key("Woman", "Wolfmother")

    assert len(calls) == 2
    assert tracks[0]["video_id"] == "selected-seed"
    assert identities.count(seed_identity) == 1
    assert len(identities) == len(set(identities))
    assert len(tracks) == 5


def test_seed_generation_keeps_every_track_when_seed_is_not_reproduced(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_generate(prompt, count, options, *, allow_shortfall=False):
        calls.append(prompt)
        assert count == 4
        tracks = [
            _seed_track_payload("track-2", "No One Knows", "Queens of the Stone Age"),
            _seed_track_payload("track-3", "Figure It Out", "Royal Blood"),
            _seed_track_payload("track-4", "Cochise", "Audioslave"),
            _seed_track_payload("track-5", "Go With the Flow", "Queens of the Stone Age"),
        ]
        return _seed_draft(prompt, count, tracks)

    monkeypatch.setattr(main_module, "_generate", fake_generate)
    client = TestClient(main_module.app)
    response = client.post("/api/playlists/generate-from-seed", json=_seed_request())

    assert response.status_code == 200
    payload = response.json()
    tracks = payload["tracks"]

    assert len(calls) == 1
    assert len(tracks) == 5
    assert tracks[0]["video_id"] == "selected-seed"
    assert {track["video_id"] for track in tracks[1:]} == {
        "track-2",
        "track-3",
        "track-4",
        "track-5",
    }


def test_seed_generation_fails_loudly_when_seed_keeps_being_reproduced(monkeypatch) -> None:
    async def fake_generate(prompt, count, options, *, allow_shortfall=False):
        tracks = [
            _seed_track_payload("alternate-upload", "Woman", "Wolfmother"),
            _seed_track_payload("track-2", "No One Knows", "Queens of the Stone Age"),
            _seed_track_payload("track-3", "Figure It Out", "Royal Blood"),
            _seed_track_payload("track-4", "Cochise", "Audioslave"),
        ]
        return _seed_draft(prompt, count, tracks)

    monkeypatch.setattr(main_module, "_generate", fake_generate)
    client = TestClient(main_module.app)
    response = client.post("/api/playlists/generate-from-seed", json=_seed_request())

    assert response.status_code == 400


def test_anchored_other_tracks_retries_when_either_anchor_reappears(monkeypatch) -> None:
    start = main_module.SeedTrack(
        video_id="start-vid", title="Start Song", artists="Start Artist"
    )
    end = main_module.SeedTrack(video_id="end-vid", title="End Song", artists="End Artist")
    calls: list[str] = []

    async def fake_generate(prompt, count, options, *, allow_shortfall=False):
        calls.append(prompt)
        assert count == 3
        if len(calls) == 1:
            tracks = [
                {"video_id": "alt-end", "title": "End Song", "artists": "End Artist"},
                {"video_id": "t2", "title": "Bridge Two", "artists": "Bridge Artist"},
                {"video_id": "t3", "title": "Bridge Three", "artists": "Bridge Artist"},
            ]
        else:
            assert "Do not include" in prompt
            tracks = [
                {"video_id": "t2", "title": "Bridge Two", "artists": "Bridge Artist"},
                {"video_id": "t3", "title": "Bridge Three", "artists": "Bridge Artist"},
                {"video_id": "t4", "title": "Bridge Four", "artists": "Bridge Artist"},
            ]
        return {"tracks": tracks}

    monkeypatch.setattr(main_module, "_generate", fake_generate)
    result, reproduced = asyncio.run(
        main_module._anchored_other_tracks(
            "bridge prompt", 3, main_module.PlaylistOptions(), [start, end]
        )
    )

    assert len(calls) == 2
    assert {t["video_id"] for t in result["tracks"]} == {"t2", "t3", "t4"}
    assert reproduced == {"video_id": "alt-end", "title": "End Song", "artists": "End Artist"}
