from __future__ import annotations

import asyncio

from backend import playlist_refinement as refinement


def _track(title: str, artist: str, video_id: str) -> dict:
    return {
        "title": title,
        "artists": artist,
        "video_id": video_id,
        "description": title,
        "reason": title,
    }


def _record() -> dict:
    tracks = [
        _track("Invece no", "Laura Pausini", "p1"),
        _track("Immobile", "Alessandra Amoroso", "a1"),
        _track("A te", "Jovanotti", "j1"),
    ]
    return {
        "id": "draft-fallback",
        "name": "Italian songs",
        "description": "Current draft",
        "prompt": "Italian pop",
        "status": "draft",
        "track_count": 3,
        "playlist": {
            "name": "Italian songs",
            "description": "Current draft",
            "prompt": "Italian pop",
            "requested_count": 3,
            "resolved_count": 3,
            "tracks": tracks,
        },
        "generation_request": {
            "mode": "prompt",
            "options": {
                "exclude_live": True,
                "exclude_covers": True,
                "exclude_remixes": True,
            },
        },
    }


def test_local_removal_recognizes_unique_surnames_from_current_playlist() -> None:
    tracks = _record()["playlist"]["tracks"]

    constraints = refinement._local_explicit_removals(
        "rimuovi le canzoni della pausini e della amoroso",
        tracks,
    )

    assert constraints.metadata.excluded_artists == [
        "Laura Pausini",
        "Alessandra Amoroso",
    ]
    assert refinement._local_explicit_removals(
        "rendila più energica",
        tracks,
    ).active is False


def test_interpreter_failure_does_not_block_soft_refinement(monkeypatch) -> None:
    record = _record()

    async def fake_interpret(config, prompt: str):
        return None

    async def fake_generate(config, prompt: str, count: int) -> dict:
        assert "più energica" in prompt
        return {
            "title": "ignored",
            "description": "ignored",
            "tracks": [
                {"artist": "Laura Pausini", "title": "Invece no"},
                {"artist": "Alessandra Amoroso", "title": "Immobile"},
                {"artist": "Jovanotti", "title": "A te"},
            ],
        }

    async def fake_resolve(candidates: list[dict], options: dict):
        assert candidates == []
        return [], []

    monkeypatch.setattr(refinement, "load_config", lambda: object())
    monkeypatch.setattr(refinement, "interpret_constraints", fake_interpret)
    monkeypatch.setattr(refinement, "generate_playlist_draft", fake_generate)
    monkeypatch.setattr(refinement, "resolve_candidates", fake_resolve)

    result = asyncio.run(refinement._build_preview(record, "rendila più energica"))

    assert result["summary"]["tracks"] == 3
    assert [track["title"] for track in result["playlist"]["tracks"]] == [
        "Invece no",
        "Immobile",
        "A te",
    ]


def test_interpreter_failure_still_enforces_local_artist_removal(monkeypatch) -> None:
    tracks = _record()["playlist"]["tracks"]

    async def fake_interpret(config, prompt: str):
        return None

    monkeypatch.setattr(refinement, "interpret_constraints", fake_interpret)

    constraints = asyncio.run(
        refinement._interpret_refinement_constraints(
            object(),
            "remove Pausini and Amoroso songs",
            tracks,
        )
    )

    assert constraints.metadata.excluded_artists == [
        "Laura Pausini",
        "Alessandra Amoroso",
    ]
    assert refinement._direct_constraint_violation(tracks[0], constraints)
    assert refinement._direct_constraint_violation(tracks[1], constraints)
    assert refinement._direct_constraint_violation(tracks[2], constraints) is None
