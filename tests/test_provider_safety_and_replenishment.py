import asyncio

import backend.favorites as favorites_module
import backend.main as main_module
from backend.config import AppConfig, api_key_matches_provider
from backend.llm import safe_error_message


def test_cross_provider_keys_are_not_considered_configured() -> None:
    assert api_key_matches_provider("gemini", "sk-or-v1-example") is False
    assert api_key_matches_provider("openrouter_free", "AIza-example") is False
    assert AppConfig(
        provider="gemini",
        api_key="sk-or-v1-example",
        model="gemini-3.6-flash",
    ).configured is False


def test_public_error_redacts_keys_and_urls() -> None:
    error = ValueError(
        "Bad request https://example.test/path?key=AIzaVerySecretKey123456789"
    )
    message = safe_error_message(error)
    assert "AIzaVerySecret" not in message
    assert "https://" not in message


def test_generate_replenishes_tracks_after_youtube_resolution(monkeypatch) -> None:
    ai_calls: list[int] = []
    resolve_calls = 0

    async def fake_generate(config, prompt, count, is_seed_generation=False):
        ai_calls.append(count)
        start = 1 if len(ai_calls) == 1 else 6
        return {
            "title": "Test Playlist",
            "description": "A test playlist.",
            "tracks": [
                {
                    "artist": f"Artist {index}",
                    "title": f"Track {index}",
                    "description": "Description.",
                    "reason": "Reason.",
                }
                for index in range(start, start + count)
            ],
        }

    async def fake_resolve(candidates, exclusions):
        nonlocal resolve_calls
        resolve_calls += 1
        selected = candidates[:2] if resolve_calls == 1 else candidates[:3]
        return (
            [
                {
                    "video_id": f"video-{item['title']}",
                    "title": item["title"],
                    "artists": item["artist"],
                    "album": "Album",
                    "duration": "3:00",
                    "thumbnail_url": "",
                    "url": "https://music.youtube.com/watch?v=test",
                    "description": item["description"],
                    "reason": item["reason"],
                }
                for item in selected
            ],
            candidates[len(selected) :],
        )

    monkeypatch.setattr(
        main_module,
        "load_config",
        lambda: AppConfig(provider="openai", api_key="sk-test", model="model"),
    )
    monkeypatch.setattr(main_module, "generate_playlist_draft", fake_generate)
    monkeypatch.setattr(main_module, "resolve_candidates", fake_resolve)

    result = asyncio.run(
        main_module._generate("A test playlist", 5, main_module.PlaylistOptions())
    )

    assert len(result["tracks"]) == 5
    assert result["resolved_count"] == 5
    # The initial draft requests a small overshoot beyond the target count so a
    # meaningful fraction of borderline requests can skip replenishment round 1 entirely.
    assert ai_calls[0] == 5 + main_module._initial_draft_overshoot(5)
    assert len(ai_calls) == 2


def test_generate_appends_a_discreet_signature_to_the_description(monkeypatch) -> None:
    async def fake_generate(config, prompt, count, is_seed_generation=False):
        return {
            "title": "Test Playlist",
            "description": "A short, punchy description.",
            "tracks": [
                {
                    "artist": f"Artist {index}",
                    "title": f"Track {index}",
                    "description": "Description.",
                    "reason": "Reason.",
                }
                for index in range(count)
            ],
        }

    async def fake_resolve(candidates, exclusions):
        return (
            [
                {
                    "video_id": f"video-{item['title']}",
                    "title": item["title"],
                    "artists": item["artist"],
                    "album": "Album",
                    "duration": "3:00",
                    "thumbnail_url": "",
                    "url": "https://music.youtube.com/watch?v=test",
                    "description": item["description"],
                    "reason": item["reason"],
                }
                for item in candidates
            ],
            [],
        )

    monkeypatch.setattr(
        main_module,
        "load_config",
        lambda: AppConfig(provider="openai", api_key="sk-test", model="model"),
    )
    monkeypatch.setattr(main_module, "generate_playlist_draft", fake_generate)
    monkeypatch.setattr(main_module, "resolve_candidates", fake_resolve)

    result = asyncio.run(
        main_module._generate("A test playlist", 5, main_module.PlaylistOptions())
    )

    assert result["description"].startswith("A short, punchy description.")
    assert "Made with PlaylistMuse" in result["description"]


def _no_ai_calls(monkeypatch):
    async def fail_generate(config, prompt, count, is_seed_generation=False):
        raise AssertionError("the AI must not be called for a pure favorite-tracks request")

    async def fail_resolve(candidates, exclusions):
        raise AssertionError("catalogue resolution must not run for pure favorite tracks")

    monkeypatch.setattr(
        main_module,
        "load_config",
        lambda: AppConfig(provider="openai", api_key="sk-test", model="model"),
    )
    monkeypatch.setattr(main_module, "generate_playlist_draft", fail_generate)
    monkeypatch.setattr(main_module, "resolve_candidates", fail_resolve)


def test_generate_pure_favorite_tracks_skips_ai_and_returns_only_bookmarked_tracks(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(favorites_module, "FAVORITES_PATH", tmp_path / "favorites.json")
    favorites_module.add_favorite_track(
        {"video_id": "vid1", "title": "Back In Black", "artists": "AC/DC"}
    )
    favorites_module.add_favorite_track(
        {"video_id": "vid2", "title": "Angie", "artists": "The Rolling Stones"}
    )
    favorites_module.add_favorite_track(
        {"video_id": "vid3", "title": "Paint It Black", "artists": "The Rolling Stones"}
    )
    _no_ai_calls(monkeypatch)

    result = asyncio.run(
        main_module._generate(
            "crea una playlist con le mie canzoni preferite", 10, main_module.PlaylistOptions()
        )
    )

    assert {t["video_id"] for t in result["tracks"]} == {"vid1", "vid2", "vid3"}
    assert result["resolved_count"] == 3
    assert result["requested_count"] == 10


def test_generate_pure_favorite_tracks_raises_when_none_are_saved(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(favorites_module, "FAVORITES_PATH", tmp_path / "favorites.json")
    _no_ai_calls(monkeypatch)

    try:
        asyncio.run(
            main_module._generate(
                "crea una playlist con le mie canzoni preferite",
                10,
                main_module.PlaylistOptions(),
            )
        )
    except ValueError as error:
        assert "haven't bookmarked" in str(error)
    else:
        raise AssertionError("expected a ValueError when no favorite tracks are saved")


def test_generate_combined_favorites_seeds_tracks_then_fills_remaining_with_ai(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(favorites_module, "FAVORITES_PATH", tmp_path / "favorites.json")
    favorites_module.add_favorite_artist("AC/DC")
    favorites_module.add_favorite_track(
        {"video_id": "vid1", "title": "Back In Black", "artists": "AC/DC"}
    )
    ai_calls: list[int] = []

    async def fake_generate(config, prompt, count, is_seed_generation=False):
        ai_calls.append(count)
        return {
            "title": "Test Playlist",
            "description": "A test playlist.",
            "tracks": [
                {
                    "artist": "AC/DC",
                    "title": f"Extra {index}",
                    "description": "Description.",
                    "reason": "Reason.",
                }
                for index in range(count)
            ],
        }

    async def fake_resolve(candidates, exclusions):
        return (
            [
                {
                    "video_id": f"video-{item['title']}",
                    "title": item["title"],
                    "artists": item["artist"],
                    "album": "Album",
                    "duration": "3:00",
                    "thumbnail_url": "",
                    "url": "https://music.youtube.com/watch?v=test",
                    "description": item["description"],
                    "reason": item["reason"],
                }
                for item in candidates
            ],
            [],
        )

    monkeypatch.setattr(
        main_module,
        "load_config",
        lambda: AppConfig(provider="openai", api_key="sk-test", model="model"),
    )
    monkeypatch.setattr(main_module, "generate_playlist_draft", fake_generate)
    monkeypatch.setattr(main_module, "resolve_candidates", fake_resolve)

    result = asyncio.run(
        main_module._generate(
            "crea una playlist con i miei preferiti", 5, main_module.PlaylistOptions()
        )
    )

    assert len(result["tracks"]) == 5
    assert result["tracks"][0]["video_id"] == "vid1"  # bookmarked track seeded first
    # only the shortfall (5 - 1 bookmarked) plus its own small overshoot was requested,
    # not the full 5 -- confirms the bookmarked track reduced what the AI was asked for.
    assert ai_calls[0] == 4 + main_module._initial_draft_overshoot(4)
