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

    async def fake_generate(config, prompt, count, is_seed_generation=False):
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


def test_prompt_generation_energy_order_wins_over_chronological_order(monkeypatch) -> None:
    """Regression test for final whole-branch review Finding 2.

    energy_order and chronological_order must be mutually exclusive at the main.py
    branching level: when a trusted energy_order is present alongside a trusted
    chronological_order, order_tracks_by_energy must fire (with chronological_direction
    passed through as a secondary, in-band refinement) and order_tracks_by_release_date
    must never be called.
    """
    energy_calls: list[dict] = []

    monkeypatch.setattr(
        main_module,
        "load_config",
        lambda: SimpleNamespace(configured=True),
    )

    async def fake_generate(config, prompt, count, is_seed_generation=False):
        return {
            "title": "Energy Playlist",
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
            "energy_order": "increasing",
            "chronological_order": "oldest_first",
            "field_confidence": {
                "energy_order": 0.99,
                "chronological_order": 0.99,
            },
        }

    def fail_if_release_date_order_called(*args, **kwargs):
        raise AssertionError(
            "order_tracks_by_release_date must never be called when a trusted "
            "energy_order is present"
        )

    async def fake_order_by_energy(tracks, direction, *, chronological_direction=None):
        energy_calls.append(
            {"direction": direction, "chronological_direction": chronological_direction}
        )
        return list(reversed(tracks))

    monkeypatch.setattr(main_module, "generate_playlist_draft", fake_generate)
    monkeypatch.setattr(main_module, "resolve_candidates", fake_resolve)
    monkeypatch.setattr(main_module, "interpret_constraints", fake_interpret)
    monkeypatch.setattr(
        main_module, "order_tracks_by_release_date", fail_if_release_date_order_called
    )
    monkeypatch.setattr(main_module, "order_tracks_by_energy", fake_order_by_energy)

    policy_token = _ACTIVE_POLICY.set(None)
    try:
        result = asyncio.run(
            main_module._generate(
                "Rock playlist with increasing energy, oldest to newest",
                2,
                main_module.PlaylistOptions(),
            )
        )
    finally:
        _ACTIVE_POLICY.reset(policy_token)

    assert energy_calls == [
        {"direction": "increasing", "chronological_direction": "oldest_first"}
    ]
    assert [track["title"] for track in result["tracks"]] == [
        "Old Song",
        "New Song",
    ]


def test_prompt_generation_energy_order_steady_ignores_chronological_order(
    monkeypatch,
) -> None:
    """Regression test for final whole-branch review Finding 2 (steady case).

    A trusted chronological_order alongside energy_order="steady" must still route
    through order_tracks_by_energy (never order_tracks_by_release_date), but with
    chronological_direction forced to None, since "steady" has no band structure to
    layer a secondary chronological sort onto.
    """
    energy_calls: list[dict] = []

    monkeypatch.setattr(
        main_module,
        "load_config",
        lambda: SimpleNamespace(configured=True),
    )

    async def fake_generate(config, prompt, count, is_seed_generation=False):
        return {
            "title": "Energy Playlist",
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
            "energy_order": "steady",
            "chronological_order": "oldest_first",
            "field_confidence": {
                "energy_order": 0.99,
                "chronological_order": 0.99,
            },
        }

    def fail_if_release_date_order_called(*args, **kwargs):
        raise AssertionError(
            "order_tracks_by_release_date must never be called when a trusted "
            "energy_order is present"
        )

    async def fake_order_by_energy(tracks, direction, *, chronological_direction=None):
        energy_calls.append(
            {"direction": direction, "chronological_direction": chronological_direction}
        )
        return list(tracks)

    monkeypatch.setattr(main_module, "generate_playlist_draft", fake_generate)
    monkeypatch.setattr(main_module, "resolve_candidates", fake_resolve)
    monkeypatch.setattr(main_module, "interpret_constraints", fake_interpret)
    monkeypatch.setattr(
        main_module, "order_tracks_by_release_date", fail_if_release_date_order_called
    )
    monkeypatch.setattr(main_module, "order_tracks_by_energy", fake_order_by_energy)

    policy_token = _ACTIVE_POLICY.set(None)
    try:
        asyncio.run(
            main_module._generate(
                "Rock playlist, keep the energy steady, oldest to newest",
                2,
                main_module.PlaylistOptions(),
            )
        )
    finally:
        _ACTIVE_POLICY.reset(policy_token)

    assert energy_calls == [{"direction": "steady", "chronological_direction": None}]


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
