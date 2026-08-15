import asyncio

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

    async def fake_generate(config, prompt, count):
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
    assert ai_calls[0] == 5
    assert len(ai_calls) == 2


def test_generate_appends_a_discreet_signature_to_the_description(monkeypatch) -> None:
    async def fake_generate(config, prompt, count):
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
