from __future__ import annotations

import asyncio
from types import SimpleNamespace

import backend.main as main_module
from backend import playlist_refinement as refinement
from backend.metadata_validation import MetadataConstraints
from backend.policy_enforcement import _ACTIVE_POLICY


def _draft_tracks() -> list[dict[str, str]]:
    return [
        {
            "artist": "Artist New",
            "title": "New Song",
            "description": "New description",
            "reason": "New reason",
        },
        {
            "artist": "Artist Old",
            "title": "Old Song",
            "description": "Old description",
            "reason": "Old reason",
        },
    ]


def _resolved(track: dict[str, str], index: int) -> dict:
    return {
        "video_id": f"video-{index}",
        "title": track["title"],
        "artists": track["artist"],
        "description": track["description"],
        "reason": track["reason"],
    }


def test_prompt_generation_applies_explicit_chronological_order(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        main_module,
        "load_config",
        lambda: SimpleNamespace(configured=True),
    )

    async def fake_generate(config, prompt, count, seed_anchor=None):
        return {
            "title": "Chronological Playlist",
            "description": "A test playlist",
            "tracks": _draft_tracks(),
        }

    async def fake_resolve(candidates, exclusions):
        return [
            _resolved(track, index)
            for index, track in enumerate(candidates, start=1)
        ], []

    async def fake_interpret(config, prompt):
        return {
            "chronological_order": "oldest_first",
            "field_confidence": {"chronological_order": 0.99},
        }

    async def fake_order(tracks, direction):
        calls.append(direction)
        return list(reversed(tracks))

    monkeypatch.setattr(main_module, "generate_playlist_draft", fake_generate)
    monkeypatch.setattr(main_module, "resolve_candidates", fake_resolve)
    monkeypatch.setattr(main_module, "interpret_constraints", fake_interpret)
    monkeypatch.setattr(main_module, "order_tracks_by_release_date", fake_order)

    policy_token = _ACTIVE_POLICY.set(None)
    try:
        result = asyncio.run(
            main_module._generate(
                "Ordina dalla più vecchia alla più recente",
                2,
                main_module.PlaylistOptions(),
            )
        )
    finally:
        _ACTIVE_POLICY.reset(policy_token)

    assert calls == ["oldest_first"]
    assert [track["title"] for track in result["tracks"]] == [
        "Old Song",
        "New Song",
    ]


def test_refinement_preview_applies_explicit_chronological_order(monkeypatch) -> None:
    current = [
        _resolved(_draft_tracks()[0], 1),
        _resolved(_draft_tracks()[1], 2),
    ]
    record = {
        "id": "draft-chronology",
        "name": "Draft",
        "description": "Draft description",
        "prompt": "Original prompt",
        "status": "draft",
        "track_count": 2,
        "playlist": {
            "name": "Draft",
            "description": "Draft description",
            "prompt": "Original prompt",
            "tracks": current,
        },
        "generation_request": {"options": {}},
    }
    calls: list[str] = []

    async def fake_constraints(config, instruction, current_tracks=None):
        return refinement._RefinementConstraints(
            MetadataConstraints(),
            chronological_order="oldest_first",
        )

    async def fake_generate(config, prompt, count):
        return {
            "title": "Ignored",
            "description": "Ignored",
            "tracks": _draft_tracks(),
        }

    async def fake_resolve(candidates, options):
        return [], []

    async def fake_order(tracks, direction):
        calls.append(direction)
        return list(reversed(tracks))

    monkeypatch.setattr(refinement, "load_config", lambda: object())
    monkeypatch.setattr(
        refinement,
        "_interpret_refinement_constraints",
        fake_constraints,
    )
    monkeypatch.setattr(refinement, "generate_playlist_draft", fake_generate)
    monkeypatch.setattr(refinement, "resolve_candidates", fake_resolve)
    monkeypatch.setattr(refinement, "order_tracks_by_release_date", fake_order)

    result = asyncio.run(
        refinement._build_preview(
            record,
            "Riordina dalla più vecchia alla più recente",
        )
    )

    assert calls == ["oldest_first"]
    assert [track["title"] for track in result["playlist"]["tracks"]] == [
        "Old Song",
        "New Song",
    ]
