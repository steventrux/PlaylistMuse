from __future__ import annotations

import asyncio

from backend import playlist_refinement as refinement


def _track(title: str, artist: str, video_id: str) -> dict:
    return {"title": title, "artists": artist, "video_id": video_id}


def _record() -> dict:
    tracks = [
        _track("A", "Artist A", "a"),
        _track("B", "Artist B", "b"),
        _track("C", "Artist C", "c"),
        _track("D", "Artist D", "d"),
        _track("E", "Artist E", "e"),
    ]
    return {
        "id": "draft-additions",
        "name": "Rock Draft",
        "description": "Draft",
        "prompt": "Melodic rock",
        "status": "draft",
        "track_count": len(tracks),
        "playlist": {
            "name": "Rock Draft",
            "description": "Draft",
            "prompt": "Melodic rock",
            "requested_count": len(tracks),
            "resolved_count": len(tracks),
            "tracks": tracks,
        },
        "generation_request": {
            "mode": "prompt",
            "options": {
                "exclude_live": False,
                "exclude_covers": True,
                "exclude_remixes": True,
            },
        },
    }


def _valid_interpretation() -> dict:
    return {
        "allowed_artists": ["Bryan Adams"],
        "excluded_artists": [],
        "allowed_albums": [],
        "excluded_albums": [],
        "release_year": None,
        "release_year_from": None,
        "release_year_to": None,
        "artist_country": None,
        "excluded_tracks": [],
        "contradictions": [],
        "constraint_status": "valid",
        "status_reasons": [],
        "field_confidence": {
            "allowed_artists": 0.99,
            "excluded_artists": 0.0,
            "allowed_albums": 0.0,
            "excluded_albums": 0.0,
            "release_year": 0.0,
            "release_year_from": 0.0,
            "release_year_to": 0.0,
            "artist_country": 0.0,
            "excluded_tracks": 0.0,
        },
        "confidence": "high",
    }


def test_quantitative_addition_retries_and_preserves_existing_positions(monkeypatch) -> None:
    record = _record()
    calls = {"generate": 0}

    async def fake_interpret(config, prompt: str) -> dict:
        return _valid_interpretation()

    async def fake_generate(config, prompt: str, count: int) -> dict:
        calls["generate"] += 1
        assert "Add exactly 2 NEW distinct tracks by Bryan Adams" in prompt
        assert "Existing tracks by that artist do not count" in prompt
        if calls["generate"] == 1:
            tracks = [
                {"artist": "Artist E", "title": "E"},
                {"artist": "Artist D", "title": "D"},
                {"artist": "Artist C", "title": "C"},
                {"artist": "Artist B", "title": "B"},
                {"artist": "Artist A", "title": "A"},
            ]
        else:
            tracks = [
                {"artist": "Artist C", "title": "C"},
                {"artist": "Bryan Adams", "title": "Heaven"},
                {"artist": "Artist A", "title": "A"},
                {"artist": "Bryan Adams", "title": "Run to You"},
                {"artist": "Artist E", "title": "E"},
            ]
        return {"title": "x", "description": "x", "tracks": tracks}

    async def fake_resolve(candidates: list[dict], options: dict) -> tuple[list[dict], list[dict]]:
        resolved = [
            _track(item["title"], item["artist"], f"resolved-{index}")
            for index, item in enumerate(candidates, start=1)
            if item["artist"] == "Bryan Adams"
        ]
        return resolved, []

    monkeypatch.setattr(refinement, "load_config", lambda: object())
    monkeypatch.setattr(refinement, "interpret_constraints", fake_interpret)
    monkeypatch.setattr(refinement, "generate_playlist_draft", fake_generate)
    monkeypatch.setattr(refinement, "resolve_candidates", fake_resolve)

    result = asyncio.run(refinement._build_preview(record, "Add 2 Bryan Adams songs"))

    assert calls["generate"] == 2
    tracks = result["playlist"]["tracks"]
    assert [track["title"] for track in tracks] == ["A", "Heaven", "C", "Run to You", "E"]
    assert [track["artists"] for track in tracks].count("Bryan Adams") == 2
    assert result["summary"] == {
        "tracks": 5,
        "kept": 3,
        "changed": 2,
        "reordered": 0,
    }


def test_final_attempt_repairs_unresolved_addition_from_catalogue(monkeypatch) -> None:
    record = _record()
    calls = {"generate": 0, "repair": 0}

    async def fake_interpret(config, prompt: str) -> dict:
        return _valid_interpretation()

    async def fake_generate(config, prompt: str, count: int) -> dict:
        calls["generate"] += 1
        return {
            "title": "x",
            "description": "x",
            "tracks": [
                {"artist": "Artist A", "title": "A"},
                {"artist": "Artist B", "title": "B"},
                {"artist": "Artist C", "title": "C"},
                {"artist": "Artist D", "title": "D"},
                {"artist": "Artist E", "title": "E"},
            ],
        }

    async def fake_resolve(candidates: list[dict], options: dict) -> tuple[list[dict], list[dict]]:
        return [], list(candidates)

    async def fake_repair(
        current_tracks: list[dict],
        refined_tracks: list[dict],
        generated_tracks: list[dict],
        targets: list,
        *,
        exclusions: dict,
        metadata_constraints,
    ) -> tuple[list[dict], list[dict]]:
        calls["repair"] += 1
        assert calls["generate"] == 3
        assert len(targets) == 1
        assert targets[0].artist == "Bryan Adams"
        assert targets[0].count == 1
        assert exclusions["exclude_covers"] is True
        repaired = [dict(track) for track in refined_tracks[:-1]]
        repaired.append(_track("Heaven", "Bryan Adams", "fallback-ba"))
        return repaired, []

    monkeypatch.setattr(refinement, "load_config", lambda: object())
    monkeypatch.setattr(refinement, "interpret_constraints", fake_interpret)
    monkeypatch.setattr(refinement, "generate_playlist_draft", fake_generate)
    monkeypatch.setattr(refinement, "resolve_candidates", fake_resolve)
    monkeypatch.setattr(refinement, "repair_artist_addition_targets", fake_repair)

    result = asyncio.run(refinement._build_preview(record, "Add one Bryan Adams song"))

    assert calls == {"generate": 3, "repair": 1}
    tracks = result["playlist"]["tracks"]
    assert [track["title"] for track in tracks] == ["A", "B", "C", "D", "Heaven"]
    assert result["summary"] == {
        "tracks": 5,
        "kept": 4,
        "changed": 1,
        "reordered": 0,
    }
