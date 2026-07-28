from fastapi.testclient import TestClient

import backend.main as main_module
from backend.config import AppConfig, api_key_slot
from backend.youtube import track_identity_key


def test_health() -> None:
    client = TestClient(main_module.app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "application": "PlaylistMuse"}


def test_openrouter_modes_share_one_api_key_slot() -> None:
    assert api_key_slot("openrouter_auto") == "openrouter"
    assert api_key_slot("openrouter_free") == "openrouter"

    config = AppConfig(provider_api_keys={"openrouter": "saved-key"})
    assert config.key_is_saved("openrouter_auto")
    assert config.key_is_saved("openrouter_free")


def test_openrouter_free_enforces_free_router_and_marks_both_modes(monkeypatch) -> None:
    saved: dict[str, AppConfig] = {}

    monkeypatch.setattr(main_module, "load_config", lambda: AppConfig())
    monkeypatch.setattr(main_module, "save_config", lambda config: saved.setdefault("config", config))

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
                {"video_id": "track-3", "title": "Figure It Out", "artists": "Royal Blood"},
                {"video_id": "track-4", "title": "Cochise", "artists": "Audioslave"},
                {"video_id": "track-5", "title": "Go With the Flow", "artists": "Queens of the Stone Age"},
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
