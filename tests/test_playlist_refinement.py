from __future__ import annotations

import asyncio

from backend import playlist_refinement as refinement


def _track(title: str, artist: str, video_id: str) -> dict:
    return {
        "title": title,
        "artists": artist,
        "video_id": video_id,
        "description": f"Description for {title}",
        "reason": f"Reason for {title}",
    }


def _record() -> dict:
    return {
        "id": "draft-1",
        "name": "Night Drive",
        "description": "Original description",
        "prompt": "70s and 80s blues rock for a night drive",
        "status": "draft",
        "track_count": 3,
        "playlist": {
            "name": "Night Drive",
            "description": "Original description",
            "prompt": "70s and 80s blues rock for a night drive",
            "requested_count": 3,
            "resolved_count": 3,
            "tracks": [
                _track("Alpha", "Artist A", "a1"),
                _track("Beta", "Artist B", "b1"),
                _track("Gamma", "Artist C", "c1"),
            ],
            "lastfm": {"available": True},
        },
        "generation_request": {
            "mode": "prompt",
            "options": {
                "exclude_live": True,
                "exclude_covers": True,
                "exclude_remixes": True,
            },
            "refinements": [
                {"prompt": "Keep it guitar-heavy", "applied_at": "2026-08-01T10:00:00+00:00"}
            ],
        },
    }


def _valid_interpretation(**overrides) -> dict:
    payload = {
        "allowed_artists": [],
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
            "allowed_artists": 0.0,
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
    payload.update(overrides)
    return payload


def test_refinement_preview_preserves_existing_resolved_tracks_and_resolves_only_new(monkeypatch) -> None:
    record = _record()
    captured: dict[str, object] = {}

    async def fake_interpret(config, prompt: str) -> dict:
        return _valid_interpretation()

    async def fake_generate(config, prompt: str, count: int) -> dict:
        captured["prompt"] = prompt
        captured["count"] = count
        return {
            "title": "Ignored AI title",
            "description": "Ignored AI description",
            "tracks": [
                {
                    "artist": "Artist A",
                    "title": "Alpha",
                    "description": "Updated Alpha description",
                    "reason": "Alpha still opens the playlist.",
                },
                {
                    "artist": "Artist D",
                    "title": "Delta",
                    "description": "A new bluesier track.",
                    "reason": "It adds the requested blues emphasis.",
                },
                {
                    "artist": "Artist C",
                    "title": "Gamma",
                    "description": "Updated Gamma description",
                    "reason": "Gamma closes the playlist.",
                },
            ],
        }

    async def fake_resolve(candidates: list[dict], options: dict) -> tuple[list[dict], list[dict]]:
        captured["candidates"] = candidates
        captured["options"] = options
        return [
            {
                "title": "Delta",
                "artists": "Artist D",
                "video_id": "d1",
                "description": "Resolved description",
                "reason": "Resolved reason",
            }
        ], []

    monkeypatch.setattr(refinement, "load_config", lambda: object())
    monkeypatch.setattr(refinement, "interpret_constraints", fake_interpret)
    monkeypatch.setattr(refinement, "generate_playlist_draft", fake_generate)
    monkeypatch.setattr(refinement, "resolve_candidates", fake_resolve)

    result = asyncio.run(refinement._build_preview(record, "More blues, less classic rock"))

    assert captured["count"] == 3
    assert "Original request:" in str(captured["prompt"])
    assert "Keep it guitar-heavy" in str(captured["prompt"])
    assert "More blues, less classic rock" in str(captured["prompt"])
    assert [item["title"] for item in captured["candidates"]] == ["Delta"]
    assert captured["options"] == {
        "exclude_live": True,
        "exclude_covers": True,
        "exclude_remixes": True,
    }

    playlist = result["playlist"]
    assert playlist["name"] == "Night Drive"
    assert playlist["description"] == "Original description"
    assert playlist["prompt"] == "70s and 80s blues rock for a night drive"
    assert "lastfm" not in playlist
    assert [track["title"] for track in playlist["tracks"]] == ["Alpha", "Delta", "Gamma"]
    assert playlist["tracks"][0]["video_id"] == "a1"
    assert playlist["tracks"][1]["video_id"] == "d1"
    assert playlist["tracks"][2]["video_id"] == "c1"
    assert result["summary"] == {
        "tracks": 3,
        "kept": 2,
        "changed": 1,
        "reordered": 0,
    }


def test_unresolved_refinement_candidates_fall_back_to_existing_draft_tracks() -> None:
    current = [
        _track("Alpha", "Artist A", "a1"),
        _track("Beta", "Artist B", "b1"),
        _track("Gamma", "Artist C", "c1"),
    ]
    generated = [
        {"artist": "Artist A", "title": "Alpha", "description": "A", "reason": "A"},
        {"artist": "Artist D", "title": "Delta", "description": "D", "reason": "D"},
        {"artist": "Artist C", "title": "Gamma", "description": "C", "reason": "C"},
    ]

    assembled = refinement._assemble_refined_tracks(current, generated, [])

    assert len(assembled) == 3
    assert [track["title"] for track in assembled] == ["Alpha", "Gamma", "Beta"]
    assert all(track.get("video_id") for track in assembled)


def test_explicit_artist_exclusion_is_hard_and_fallback_cannot_reinsert_it(monkeypatch) -> None:
    record = _record()
    calls = {"generate": 0}

    async def fake_interpret(config, prompt: str) -> dict:
        return _valid_interpretation(
            excluded_artists=["Artist B"],
            field_confidence={
                "allowed_artists": 0.0,
                "excluded_artists": 0.99,
                "allowed_albums": 0.0,
                "excluded_albums": 0.0,
                "release_year": 0.0,
                "release_year_from": 0.0,
                "release_year_to": 0.0,
                "artist_country": 0.0,
                "excluded_tracks": 0.0,
            },
        )

    async def fake_generate(config, prompt: str, count: int) -> dict:
        calls["generate"] += 1
        assert "Excluded artists: Artist B" in prompt
        if calls["generate"] == 1:
            tracks = [
                {"artist": "Artist A", "title": "Alpha", "description": "A", "reason": "A"},
                {"artist": "Artist B", "title": "Beta", "description": "B", "reason": "B"},
                {"artist": "Artist C", "title": "Gamma", "description": "C", "reason": "C"},
            ]
        else:
            tracks = [
                {"artist": "Artist A", "title": "Alpha", "description": "A", "reason": "A"},
                {"artist": "Artist D", "title": "Delta", "description": "D", "reason": "D"},
                {"artist": "Artist C", "title": "Gamma", "description": "C", "reason": "C"},
            ]
        return {"title": "x", "description": "x", "tracks": tracks}

    async def fake_resolve(candidates: list[dict], options: dict) -> tuple[list[dict], list[dict]]:
        resolved = [
            _track(item["title"], item["artist"], "d1")
            for item in candidates
            if item["artist"] == "Artist D"
        ]
        return resolved, []

    monkeypatch.setattr(refinement, "load_config", lambda: object())
    monkeypatch.setattr(refinement, "interpret_constraints", fake_interpret)
    monkeypatch.setattr(refinement, "generate_playlist_draft", fake_generate)
    monkeypatch.setattr(refinement, "resolve_candidates", fake_resolve)

    result = asyncio.run(refinement._build_preview(record, "rimuovi le canzoni di Artist B"))

    assert calls["generate"] == 2
    assert [track["artists"] for track in result["playlist"]["tracks"]] == [
        "Artist A",
        "Artist D",
        "Artist C",
    ]
    assert all(track["artists"] != "Artist B" for track in result["playlist"]["tracks"])


def test_direct_exclusion_guard_rejects_forbidden_artist_and_track() -> None:
    metadata = refinement.MetadataConstraints(excluded_artists=["Laura Pausini"])
    constraints = refinement._RefinementConstraints(
        metadata=metadata,
        excluded_tracks=({"artist": "Elisa", "title": "Luce"},),
    )

    assert refinement._direct_constraint_violation(
        _track("La solitudine", "Laura Pausini", "p1"), constraints
    )
    assert refinement._direct_constraint_violation(
        _track("Luce", "Elisa", "e1"), constraints
    )
    assert refinement._direct_constraint_violation(
        _track("Un'emozione per sempre", "Eros Ramazzotti", "r1"), constraints
    ) is None


def test_published_playlists_cannot_be_refined() -> None:
    record = _record()
    record["status"] = "published"

    try:
        refinement._require_draft(record)
    except Exception as error:
        assert getattr(error, "status_code", None) == 409
        assert "Only draft playlists" in str(getattr(error, "detail", ""))
    else:
        raise AssertionError("Published playlist refinement should be rejected")


def test_refinement_instruction_is_normalized() -> None:
    request = refinement.RefinementInstruction(
        instruction="  More   blues,\n less classic rock  "
    )
    assert request.instruction == "More blues, less classic rock"
