from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace

from backend import generation_runtime, llm
from backend.artist_quota_detection import (
    extract_artist_minimum_quotas,
    quota_deficits,
)
from backend.metadata_validation import MetadataConstraints
from backend.playlist_studio import (
    _effective_recording_policy,
    _repair_artist_quota_deficits,
)
from backend.prompt_validation import PromptAssessment
from backend.recording_variants import RecordingVariantPolicy


def _track(artist: str, title: str) -> dict[str, str]:
    return {
        "artist": artist,
        "artists": artist,
        "title": title,
        "video_id": f"{artist}-{title}".casefold().replace(" ", "-"),
    }


def _record(prompt: str, tracks: list[dict[str, str]]) -> dict:
    return {
        "id": "quality-test",
        "name": "Quality test",
        "description": "",
        "prompt": prompt,
        "track_count": len(tracks),
        "playlist": {
            "name": "Quality test",
            "description": "",
            "prompt": prompt,
            "tracks": deepcopy(tracks),
            "requested_count": len(tracks),
            "resolved_count": len(tracks),
        },
        "generation_request": {
            "options": {
                "exclude_live": False,
                "exclude_covers": True,
                "exclude_remixes": True,
            }
        },
    }


def test_generation_runtime_activates_compact_independent_artist_quotas(monkeypatch) -> None:
    prompt = "the playlist must have 2 metallica, 2 guns n' roses and 2 ac/dc tracks"
    captured: dict[str, object] = {}

    async def fake_assess(config, request: str) -> PromptAssessment:
        assert request == prompt
        return PromptAssessment(status="valid", interpretation={})

    async def fake_recording_policy(config, request: str) -> RecordingVariantPolicy:
        return RecordingVariantPolicy()

    async def fake_canonicalize(payload):
        return payload or {}

    async def fake_generate(config, submitted: str, count: int) -> dict:
        captured["prompt"] = submitted
        captured["count"] = count
        return {
            "title": "Quota test",
            "description": "",
            "tracks": [
                {"artist": "Metallica", "title": "M1"},
                {"artist": "Metallica", "title": "M2"},
                {"artist": "Guns N' Roses", "title": "G1"},
                {"artist": "Guns N' Roses", "title": "G2"},
                {"artist": "AC/DC", "title": "A1"},
                {"artist": "AC/DC", "title": "A2"},
            ],
        }

    import backend.entity_resolution as entity_resolution
    import backend.prompt_validation as prompt_validation
    import backend.recording_variants as recording_variants

    monkeypatch.setattr(prompt_validation, "assess_prompt", fake_assess)
    monkeypatch.setattr(recording_variants, "interpret_recording_policy", fake_recording_policy)
    monkeypatch.setattr(entity_resolution, "canonicalize_interpretation", fake_canonicalize)
    monkeypatch.setattr(llm, "generate_playlist_draft", fake_generate)

    result = asyncio.run(generation_runtime.generate_playlist_draft(object(), prompt, 6))

    active = list(generation_runtime._ACTIVE_RESOLUTION_QUOTAS.get())
    assert [(item.artist, item.minimum) for item in active] == [
        ("metallica", 2),
        ("guns n' roses", 2),
        ("ac/dc", 2),
    ]
    assert captured["count"] == 6
    submitted = str(captured["prompt"])
    assert "at least 2 tracks by metallica" in submitted
    assert "at least 2 tracks by guns n' roses" in submitted
    assert "at least 2 tracks by ac/dc" in submitted
    assert quota_deficits(result["tracks"], active) == []


def test_studio_repairs_a_preview_that_ignores_compact_artist_quotas(monkeypatch) -> None:
    instruction = "the playlist must have 2 metallica, 2 guns n' roses and 2 ac/dc tracks"
    source = [_track(f"Artist {index}", f"Old {index}") for index in range(1, 7)]
    record = _record("A rock playlist", source)
    result = {
        "playlist": deepcopy(record["playlist"]),
        "summary": {"tracks": 6, "kept": 6, "changed": 0, "reordered": 0},
        "studio": {"target_positions": [], "locked_positions": [], "editable_positions": list(range(1, 7))},
    }
    quotas = extract_artist_minimum_quotas(instruction)

    async def fake_constraints(config, request: str, current_tracks):
        assert request == instruction
        return SimpleNamespace(metadata=MetadataConstraints())

    async def fake_repair(
        current_tracks,
        refined_tracks,
        generated_tracks,
        targets,
        *,
        exclusions,
        metadata_constraints,
    ):
        assert [(target.artist, target.count) for target in targets] == [
            ("metallica", 2),
            ("guns n' roses", 2),
            ("ac/dc", 2),
        ]
        assert exclusions["exclude_live"] is False
        return [
            _track("Metallica", "M1"),
            _track("Metallica", "M2"),
            _track("Guns N' Roses", "G1"),
            _track("Guns N' Roses", "G2"),
            _track("AC/DC", "A1"),
            _track("AC/DC", "A2"),
        ], []

    import backend.playlist_studio as studio

    monkeypatch.setattr(studio, "_interpret_refinement_constraints", fake_constraints)
    monkeypatch.setattr(studio, "repair_artist_addition_targets", fake_repair)
    monkeypatch.setattr(studio, "_validate_direct_constraints", lambda tracks, constraints: None)
    monkeypatch.setattr(
        studio,
        "_generation_options",
        lambda current: SimpleNamespace(
            model_dump=lambda: {
                "exclude_live": False,
                "exclude_covers": True,
                "exclude_remixes": True,
            }
        ),
    )
    monkeypatch.setattr(studio, "load_config", lambda: object())

    repaired = asyncio.run(
        _repair_artist_quota_deficits(
            record,
            result,
            instruction,
            list(range(1, 7)),
            quotas,
        )
    )

    assert quota_deficits(repaired["playlist"]["tracks"], quotas) == []
    assert repaired["summary"]["changed"] == 6


def test_studio_inherits_original_recording_policy_until_explicitly_superseded(monkeypatch) -> None:
    original = "Create a playlist of rock music with only live versions"
    record = _record(original, [_track("Artist", "Song (Live)")])
    calls: list[str] = []

    async def fake_interpret(config, request: str) -> RecordingVariantPolicy:
        calls.append(request)
        if request == "make it heavier":
            return RecordingVariantPolicy()
        if request == original:
            return RecordingVariantPolicy(required=frozenset({"live"}))
        if request == "use only studio versions":
            return RecordingVariantPolicy(excluded=frozenset({"live"}))
        raise AssertionError(request)

    import backend.playlist_studio as studio

    monkeypatch.setattr(studio, "load_config", lambda: object())
    monkeypatch.setattr(studio, "interpret_recording_policy", fake_interpret)

    inherited = asyncio.run(_effective_recording_policy(record, "make it heavier"))
    assert inherited.required == frozenset({"live"})
    assert inherited.override_exclusions is True
    assert calls == ["make it heavier", original]

    calls.clear()
    superseded = asyncio.run(_effective_recording_policy(record, "use only studio versions"))
    assert superseded.excluded == frozenset({"live"})
    assert superseded.required == frozenset()
    assert superseded.override_exclusions is True
    assert calls == ["use only studio versions"]
