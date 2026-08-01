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


def test_prompt_generation_uses_lastfm_as_ai_context_without_fixed_quota(monkeypatch) -> None:
    prompts: list[str] = []
    first_draft = _draft(
        [
            ("Anchor Artist", "Anchor Track"),
            ("First Pass Artist", "First Pass Track"),
        ],
        title="First Pass",
    )
    final_draft = _draft(
        [
            ("Last.fm Artist", "Discovery Track"),
            ("Independent Artist", "Independent Track"),
        ],
        title="Final Guided Playlist",
    )
    lastfm_candidates = [
        {
            "artist": "Last.fm Artist",
            "title": "Discovery Track",
            "source": "lastfm",
            "lastfm_strategy": "similar_track",
            "lastfm_match": "0.91",
            "anchor_artist": "Anchor Artist",
            "anchor_title": "Anchor Track",
        },
        {
            "artist": "Unused Last.fm Artist",
            "title": "Choose a suitable track by this artist",
            "source": "lastfm",
            "lastfm_strategy": "similar_artist",
            "lastfm_match": "0.75",
            "anchor_artist": "First Pass Artist",
            "anchor_title": "First Pass Track",
        },
    ]

    monkeypatch.setattr(
        main_module,
        "load_config",
        lambda: SimpleNamespace(configured=True),
    )

    async def fake_generate(config, prompt, count):
        prompts.append(prompt)
        return first_draft if len(prompts) == 1 else final_draft

    async def fake_discover(anchors, *, limit=40, max_anchors=3):
        assert anchors == [
            {"artist": "Anchor Artist", "title": "Anchor Track"},
            {"artist": "First Pass Artist", "title": "First Pass Track"},
        ]
        assert limit >= 20
        return lastfm_candidates

    async def fake_resolve(candidates, exclusions):
        return [
            _resolved(candidate, index)
            for index, candidate in enumerate(candidates, start=1)
        ], []

    def forbidden_fixed_blend(*args, **kwargs):
        raise AssertionError("The old fixed Last.fm quota must not be used")

    monkeypatch.setattr(main_module, "generate_playlist_draft", fake_generate)
    monkeypatch.setattr(main_module, "discover_from_anchors", fake_discover)
    monkeypatch.setattr(main_module, "resolve_candidates", fake_resolve)
    monkeypatch.setattr(main_module, "_blend_candidates", forbidden_fixed_blend)

    result = asyncio.run(
        main_module._generate(
            "Italian electronic pop for a summer drive",
            2,
            main_module.PlaylistOptions(),
        )
    )

    assert len(prompts) == 2
    assert "Italian electronic pop for a summer drive" in prompts[1]
    assert "Last.fm collaborative-listening evidence" in prompts[1]
    assert "There is no quota" in prompts[1]
    assert "Last.fm Artist — Discovery Track" in prompts[1]
    assert result["name"] == "Final Guided Playlist"

    diagnostics = result["lastfm"]
    assert diagnostics["available"] is True
    assert diagnostics["guidance_applied"] is True
    assert diagnostics["suggestions"] == 2
    assert diagnostics["selected"] == 1
    assert diagnostics["represented_artists"] == 1
    assert diagnostics["strategies"] == ["similar_artist", "similar_track"]
    assert diagnostics["anchors"] == [
        {
            "artist": "Anchor Artist",
            "title": "Anchor Track",
            "kind": "ai_draft",
        },
        {
            "artist": "First Pass Artist",
            "title": "First Pass Track",
            "kind": "ai_draft",
        },
    ]
    assert diagnostics["signals"][0] == {
        "artist": "Last.fm Artist",
        "title": "Discovery Track",
        "strategy": "similar_track",
        "match": "0.91",
        "selected": True,
        "artist_represented": True,
        "anchor": {
            "artist": "Anchor Artist",
            "title": "Anchor Track",
        },
    }
    assert diagnostics["signals"][1]["title"] is None
    assert diagnostics["signals"][1]["selected"] is False
    assert diagnostics["signals"][1]["artist_represented"] is False

    assert result["tracks"][0]["source"] == "lastfm"
    assert result["tracks"][0]["lastfm_strategy"] == "similar_track"
    assert "source" not in result["tracks"][1]


def test_ai_can_ignore_all_lastfm_suggestions(monkeypatch) -> None:
    calls = 0
    lastfm_candidates = [
        {
            "artist": "Suggested Artist",
            "title": "Suggested Track",
            "source": "lastfm",
            "lastfm_strategy": "similar_track",
            "lastfm_match": "0.9",
        }
    ]

    monkeypatch.setattr(
        main_module,
        "load_config",
        lambda: SimpleNamespace(configured=True),
    )

    async def fake_generate(config, prompt, count):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _draft([("Anchor Artist", "Anchor Track")])
        return _draft(
            [
                ("Independent Artist A", "Independent Track A"),
                ("Independent Artist B", "Independent Track B"),
            ]
        )

    async def fake_discover(anchors, *, limit=40, max_anchors=3):
        return lastfm_candidates

    async def fake_resolve(candidates, exclusions):
        return [
            _resolved(candidate, index)
            for index, candidate in enumerate(candidates, start=1)
        ], []

    monkeypatch.setattr(main_module, "generate_playlist_draft", fake_generate)
    monkeypatch.setattr(main_module, "discover_from_anchors", fake_discover)
    monkeypatch.setattr(main_module, "resolve_candidates", fake_resolve)

    result = asyncio.run(
        main_module._generate(
            "A tightly focused prompt",
            2,
            main_module.PlaylistOptions(),
        )
    )

    assert result["lastfm"]["available"] is True
    assert result["lastfm"]["suggestions"] == 1
    assert result["lastfm"]["selected"] == 0
    assert result["lastfm"]["signals"][0]["selected"] is False
    assert all(track.get("source") != "lastfm" for track in result["tracks"])


def test_similar_artist_signal_reports_artist_representation(monkeypatch) -> None:
    calls = 0
    artist_signal = {
        "artist": "Related Artist",
        "title": "Choose a suitable track by this artist",
        "source": "lastfm",
        "lastfm_strategy": "similar_artist",
        "lastfm_match": "0.82",
    }

    monkeypatch.setattr(
        main_module,
        "load_config",
        lambda: SimpleNamespace(configured=True),
    )

    async def fake_generate(config, prompt, count):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _draft([("Anchor Artist", "Anchor Track")])
        return _draft([("Related Artist", "AI Chosen Song")])

    async def fake_discover(anchors, *, limit=40, max_anchors=3):
        return [artist_signal]

    async def fake_resolve(candidates, exclusions):
        return [_resolved(candidates[0], 1)], []

    monkeypatch.setattr(main_module, "generate_playlist_draft", fake_generate)
    monkeypatch.setattr(main_module, "discover_from_anchors", fake_discover)
    monkeypatch.setattr(main_module, "resolve_candidates", fake_resolve)

    result = asyncio.run(
        main_module._generate(
            "A discovery-oriented playlist",
            1,
            main_module.PlaylistOptions(),
        )
    )

    assert result["lastfm"]["selected"] == 0
    assert result["lastfm"]["represented_artists"] == 1
    assert result["lastfm"]["signals"][0]["artist_represented"] is True
    assert "source" not in result["tracks"][0]


def test_seed_context_skips_prompt_anchor_discovery(monkeypatch) -> None:
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

    monkeypatch.setattr(
        main_module,
        "load_config",
        lambda: SimpleNamespace(configured=True),
    )

    async def fake_generate(config, prompt, count):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _draft([("First Artist", "First Track")])
        return _draft([("Seed Related Artist", "Seed Related Track")])

    async def forbidden_prompt_discovery(*args, **kwargs):
        raise AssertionError("Seed discovery should be used before prompt anchors")

    async def fake_resolve(candidates, exclusions):
        return [_resolved(candidates[0], 1)], []

    monkeypatch.setattr(main_module, "generate_playlist_draft", fake_generate)
    monkeypatch.setattr(main_module, "discover_from_anchors", forbidden_prompt_discovery)
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
    assert result["lastfm"]["selected"] == 1
    assert result["lastfm"]["anchors"] == [
        {
            "artist": "Seed Artist",
            "title": "Seed Track",
            "kind": "seed",
        }
    ]
    assert result["tracks"][0]["lastfm_strategy"] == "similar_track"
