import asyncio

import pytest

from backend.metadata_validation import (
    MetadataConstraints,
    TrackMetadata,
    ValidationResult,
    active_constraints,
    activate_constraints_from_prompt,
)
from backend.youtube import _metadata_filter


@pytest.fixture(autouse=True)
def reset_metadata_constraints():
    activate_constraints_from_prompt("generic playlist")
    yield
    activate_constraints_from_prompt("generic playlist")


def test_constraint_context_covers_generation_prompt_shapes():
    activate_constraints_from_prompt("relaxing road music")
    assert not active_constraints().active

    constraints = activate_constraints_from_prompt(
        "Original playlist request: Italian artists released in 2026 only"
    )

    assert constraints.release_year == 2026
    assert constraints.artist_country == "IT"


def test_metadata_filter_is_bypassed_for_generic_prompts(monkeypatch):
    activate_constraints_from_prompt("relaxing music for a journey on the road")

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("metadata lookup should not run")

    monkeypatch.setattr("backend.youtube.validate_candidate", fail_if_called)
    candidates = [{"artist": "Artist", "title": "Song"}]

    accepted, rejected = asyncio.run(_metadata_filter(candidates))

    assert accepted == candidates
    assert rejected == []


def test_metadata_filter_rejects_invalid_and_unknown_candidates(monkeypatch):
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

    monkeypatch.setattr("backend.youtube._read_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.youtube.validate_candidate", fake_validate)
    candidates = [
        {"artist": "Artist", "title": "Valid"},
        {"artist": "Artist", "title": "Old"},
        {"artist": "Artist", "title": "Unknown"},
    ]

    accepted, rejected = asyncio.run(_metadata_filter(candidates))

    assert [candidate["title"] for candidate in accepted] == ["Valid"]
    assert accepted[0]["metadata_validation"]["original_release_year"] == 2026
    assert [candidate["title"] for candidate in rejected] == ["Old", "Unknown"]
    assert rejected[0]["metadata_validation"]["status"] == "invalid"
    assert rejected[1]["metadata_validation"]["status"] == "unknown"


def test_metadata_filter_deduplicates_candidates_before_lookup(monkeypatch):
    activate_constraints_from_prompt("songs released in 2026 only")
    calls = 0

    async def fake_validate(candidate, constraints, client=None):
        nonlocal calls
        calls += 1
        return ValidationResult(
            status="valid",
            violations=[],
            metadata=TrackMetadata(
                artist=candidate["artist"],
                title=candidate["title"],
                original_release_year=2026,
                match_score=0.95,
                confidence="high",
            ),
        )

    monkeypatch.setattr("backend.youtube._read_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.youtube.validate_candidate", fake_validate)
    candidates = [
        {"artist": "Artist", "title": "Song"},
        {"artist": "artist", "title": "song"},
    ]

    accepted, rejected = asyncio.run(_metadata_filter(candidates))

    assert calls == 1
    assert len(accepted) == 1
    assert rejected == []


def test_cached_metadata_does_not_consume_lookup_budget(monkeypatch):
    activate_constraints_from_prompt("songs released in 2026 only")

    cached = TrackMetadata(
        artist="Cached Artist",
        title="Cached Song",
        original_release_year=2026,
        match_score=0.96,
        confidence="high",
    )

    monkeypatch.setenv("METADATA_VALIDATION_MAX_LOOKUPS", "0")
    monkeypatch.setattr("backend.youtube._read_cache", lambda *args, **kwargs: cached)

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("cached metadata must not trigger a network lookup")

    monkeypatch.setattr("backend.youtube.validate_candidate", fail_if_called)

    accepted, rejected = asyncio.run(
        _metadata_filter([{"artist": "Cached Artist", "title": "Cached Song"}])
    )

    assert len(accepted) == 1
    assert rejected == []


def test_metadata_filter_marks_candidates_beyond_budget_unknown(monkeypatch):
    activate_constraints_from_prompt("songs released in 2026 only")
    calls = 0

    async def fake_validate(candidate, constraints, client=None):
        nonlocal calls
        calls += 1
        return ValidationResult(
            status="valid",
            violations=[],
            metadata=TrackMetadata(
                artist=candidate["artist"],
                title=candidate["title"],
                original_release_year=2026,
                match_score=0.95,
                confidence="high",
            ),
        )

    monkeypatch.setenv("METADATA_VALIDATION_MAX_LOOKUPS", "1")
    monkeypatch.setattr("backend.youtube._read_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.youtube.validate_candidate", fake_validate)

    accepted, rejected = asyncio.run(
        _metadata_filter(
            [
                {"artist": "Artist A", "title": "Song A"},
                {"artist": "Artist B", "title": "Song B"},
            ]
        )
    )

    assert calls == 1
    assert [candidate["title"] for candidate in accepted] == ["Song A"]
    assert rejected[0]["title"] == "Song B"
    assert rejected[0]["metadata_validation"]["status"] == "unknown"
    assert "Metadata lookup budget exceeded" in rejected[0]["metadata_validation"]["warnings"]


def test_replacement_prompt_shape_preserves_metadata_constraints():
    constraints = activate_constraints_from_prompt(
        "Suggest replacements. Original playlist request: Italian artists from 2026 only."
    )

    assert constraints == MetadataConstraints(release_year=2026, artist_country="IT")
