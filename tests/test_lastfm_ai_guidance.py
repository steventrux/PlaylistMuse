from __future__ import annotations

import asyncio
from types import SimpleNamespace

import backend.main as main_module


def _draft(tracks: list[tuple[str, str]], title: str = "Guided Playlist") -> dict:
    return {
        "title": title,
        "description": "A coherent playlist shaped by musical judgment and listening data.",
        "tracks": [
            {
                "artist": artist,
                "title": track,
                "description": f"Description for {track}.",
                "reason": f"Reason for {track}.",
            }
            for artist, track in tracks
        ],
    }


def _resolved(candidate: dict[str, str], index: int) -> dict:
    track = {
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
    for key in ("source", "lastfm_strategy"):
        if candidate.get(key):
            track[key] = candidate[key]
    return track


def _isolate_generation_dependencies(monkeypatch) -> None:
    monkeypatch.setattr(
        main_module,
        "load_config",
        lambda: SimpleNamespace(configured=True),
    )

    async def no_ordering_interpretation(config, prompt):
        return None

    monkeypatch.setattr(
        main_module,
        "interpret_constraints",
        no_ordering_interpretation,
    )


def test_represented_artist_count_is_unique_across_multiple_signals() -> None:
    candidates = [
        {
            "artist": "Led Zeppelin",
            "title": "Bring It on Home",
            "lastfm_strategy": "similar_track",
        },
        {
            "artist": "Led Zeppelin",
            "title": "What Is and What Should Never Be",
            "lastfm_strategy": "similar_track",
        },
        {
            "artist": "Steppenwolf",
            "title": "Born to Be Wild",
            "lastfm_strategy": "similar_track",
        },
    ]
    selected_tracks = [
        {"artists": "Led Zeppelin", "title": "Moby Dick"},
        {"artists": "John Kay, Steppenwolf", "title": "Magic Carpet Ride"},
    ]

    diagnostics = main_module._lastfm_summary(
        [],
        candidates,
        selected_tracks,
        guidance_applied=True,
    )

    assert diagnostics["represented_signals"] == 3
    assert diagnostics["represented_artists"] == 2
    assert all(signal["artist_represented"] for signal in diagnostics["signals"])


def test_seed_context_uses_supplied_lastfm_signals(monkeypatch) -> None:
    seed_signals = [
        {
            "artist": "Seed Related Artist",
            "title": "Seed Related Track",
            "source": "lastfm",
            "lastfm_strategy": "similar_track",
            "lastfm_match": "0.8",
        }
    ]
    calls = 0

    _isolate_generation_dependencies(monkeypatch)

    async def fake_generate(config, prompt, count):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _draft([("First Artist", "First Track")])
        assert "Last.fm seed evidence" in prompt
        return _draft([("Seed Related Artist", "Seed Related Track")])

    async def fake_resolve(candidates, exclusions):
        return [_resolved(candidates[0], 1)], []

    monkeypatch.setattr(main_module, "generate_playlist_draft", fake_generate)
    monkeypatch.setattr(main_module, "resolve_candidates", fake_resolve)

    recommendation_token = main_module._SEED_RECOMMENDATIONS.set(tuple(seed_signals))
    anchor_token = main_module._SEED_ANCHORS.set(
        (
            {
                "artist": "Seed Artist",
                "title": "Seed Track",
                "kind": "seed",
            },
        )
    )
    try:
        result = asyncio.run(
            main_module._generate(
                "A playlist inspired by a seed",
                1,
                main_module.PlaylistOptions(),
            )
        )
    finally:
        main_module._SEED_ANCHORS.reset(anchor_token)
        main_module._SEED_RECOMMENDATIONS.reset(recommendation_token)

    assert calls == 2
    assert result["lastfm"]["guidance_applied"] is True
    assert result["lastfm"]["selected"] == 1
    assert result["lastfm"]["represented_signals"] == 1
    assert result["lastfm"]["represented_artists"] == 1
    assert result["lastfm"]["anchors"] == [
        {
            "artist": "Seed Artist",
            "title": "Seed Track",
            "kind": "seed",
        }
    ]
    assert result["tracks"][0]["lastfm_strategy"] == "similar_track"
