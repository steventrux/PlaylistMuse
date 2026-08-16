from __future__ import annotations

import asyncio
from types import SimpleNamespace

import backend.lastfm_discovery as lastfm_discovery
import backend.main as main_module


def _draft() -> dict:
    return {
        "title": "Single Pass Playlist",
        "description": "A focused playlist.",
        "tracks": [
            {
                "artist": "Artist A",
                "title": "Track A",
                "description": "Description A",
                "reason": "Reason A",
            },
            {
                "artist": "Artist B",
                "title": "Track B",
                "description": "Description B",
                "reason": "Reason B",
            },
        ],
    }


def _resolved(candidate: dict[str, str], index: int) -> dict:
    return {
        "video_id": f"video-{index}",
        "title": candidate["title"],
        "artists": candidate["artist"],
        "album": "Album",
        "duration": "3:30",
        "thumbnail_url": "",
        "url": f"https://music.youtube.com/watch?v=video-{index}",
        "description": candidate.get("description", ""),
        "reason": candidate.get("reason", ""),
    }


def test_free_prompt_skips_lastfm_discovery_and_second_generation(monkeypatch) -> None:
    generation_calls: list[str] = []

    monkeypatch.setattr(
        main_module,
        "load_config",
        lambda: SimpleNamespace(configured=True),
    )

    async def fake_generate(config, prompt, count, is_seed_generation=False):
        generation_calls.append(prompt)
        return _draft()

    async def forbidden_prompt_discovery(*args, **kwargs):
        raise AssertionError("Free prompts must not enter Last.fm prompt discovery")

    async def fake_resolve(candidates, exclusions):
        return [
            _resolved(candidate, index)
            for index, candidate in enumerate(candidates, start=1)
        ], []

    async def no_ordering(config, prompt):
        return None

    monkeypatch.setattr(main_module, "generate_playlist_draft", fake_generate)
    monkeypatch.setattr(lastfm_discovery, "discover_from_anchors", forbidden_prompt_discovery)
    monkeypatch.setattr(main_module, "resolve_candidates", fake_resolve)
    monkeypatch.setattr(main_module, "interpret_constraints", no_ordering)

    result = asyncio.run(
        main_module._generate(
            "Italian party music from 2000 onward",
            2,
            main_module.PlaylistOptions(),
        )
    )

    assert len(generation_calls) == 1
    assert result["name"] == "Single Pass Playlist"
    assert result["lastfm"]["available"] is False
    assert result["lastfm"]["guidance_applied"] is False
