from types import SimpleNamespace

import pytest

from backend import llm
from backend.metadata_validation import (
    MetadataConstraints,
    TrackMetadata,
    ValidationResult,
    active_constraints,
    activate_constraints_from_prompt,
)
from backend.youtube import _metadata_filter


@pytest.mark.asyncio
async def test_generation_wrapper_activates_constraints(monkeypatch):
    captured = {}

    async def fake_original(config, prompt, count):
        captured["constraints"] = active_constraints()
        return {"title": "Test", "description": "Test", "tracks": []}

    wrapped = llm.generate_playlist_draft
    original_closure = wrapped.__wrapped__
    monkeypatch.setattr(wrapped, "__wrapped__", fake_original, raising=False)

    # The installed wrapper closes over the original function, so verify the public
    # contract directly and restore a harmless implementation around its dependency.
    monkeypatch.setattr(llm, "generate_playlist_draft", wrapped)
    activate_constraints_from_prompt("relaxing road music")
    assert not active_constraints().active

    # Constraint extraction used by the wrapper must recognize the complete prompt
    # shapes used by initial generation, replenishment and replacement.
    activate_constraints_from_prompt(
        "Original playlist request: Italian artists released in 2026 only"
    )
    constraints = active_constraints()
    assert constraints.release_year == 2026
    assert constraints.artist_country == "IT"
    assert original_closure is not None


@pytest.mark.asyncio
async def test_metadata_filter_is_bypassed_for_generic_prompts(monkeypatch):
    activate_constraints_from_prompt("relaxing music for a journey on the road")

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("metadata lookup should not run")

    monkeypatch.setattr("backend.youtube.validate_candidate", fail_if_called)
    candidates = [{"artist": "Artist", "title": "Song"}]

    accepted, rejected = await _metadata_filter(candidates)

    assert accepted == candidates
    assert rejected == []


@pytest.mark.asyncio
async def test_metadata_filter_rejects_invalid_and_unknown_candidates(monkeypatch):
    activate_constraints_from_prompt("songs released in 2026 only")

    async def fake_validate(candidate, constraints, client=None):
        if candidate["title"] == "Valid":
            return ValidationResult(
                status="valid",
                violations=[],
                metadata=TrackMetadata(
                    artist=candidate["artist"],
                    title=candidate["title"],
                    original_release_year=2026,
                    match_score=0.96,
                    confidence="high",
                ),
            )
        if candidate["title"] == "Old":
            return ValidationResult(
                status="invalid",
                violations=["release year 2024 does not match 2026"],
                metadata=TrackMetadata(
                    artist=candidate["artist"],
                    title=candidate["title"],
                    original_release_year=2024,
                    match_score=0.95,
                    confidence="high",
                ),
            )
        return ValidationResult(
            status="unknown",
            violations=[],
            metadata=TrackMetadata(
                artist=candidate["artist"],
                title=candidate["title"],
                match_score=0.0,
                confidence="low",
                warnings=["No MusicBrainz match"],
            ),
        )

    monkeypatch.setattr("backend.youtube.validate_candidate", fake_validate)
    candidates = [
        {"artist": "Artist", "title": "Valid"},
        {"artist": "Artist", "title": "Old"},
        {"artist": "Artist", "title": "Unknown"},
    ]

    accepted, rejected = await _metadata_filter(candidates)

    assert [candidate["title"] for candidate in accepted] == ["Valid"]
    assert accepted[0]["metadata_validation"]["original_release_year"] == 2026
    assert [candidate["title"] for candidate in rejected] == ["Old", "Unknown"]
    assert rejected[0]["metadata_validation"]["status"] == "invalid"
    assert rejected[1]["metadata_validation"]["status"] == "unknown"


def test_replacement_prompt_shape_preserves_metadata_constraints():
    constraints = activate_constraints_from_prompt(
        "Suggest replacements. Original playlist request: Italian artists from 2026 only."
    )

    assert constraints == MetadataConstraints(release_year=2026, artist_country="IT")
