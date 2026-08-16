import asyncio

import pytest

from backend.metadata_validation import (
    MetadataConstraints,
    TrackMetadata,
    ValidationResult,
    active_constraints,
    activate_constraints,
    activate_constraints_from_prompt,
    validate_metadata,
)
from backend.reccobeats_selector import deterministic_reccobeats_draft
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

    monkeypatch.setattr("backend.youtube.validate_candidate", fake_validate)
    candidates = [
        {"artist": "Artist", "title": "Song"},
        {"artist": "artist", "title": "song"},
    ]

    accepted, rejected = asyncio.run(_metadata_filter(candidates))

    assert calls == 1
    assert len(accepted) == 1
    assert rejected == []


def test_zero_lookup_budget_rejects_rather_than_using_a_stale_cache_shortcut(monkeypatch):
    """`_metadata_filter` used to have its own `_read_cache` fast path that accepted a
    candidate straight from cache without ever calling `validate_candidate()` -- even
    under a zero lookup budget. That was removed (2026-08-15) because a cache hit could
    carry metadata validated for a different request's constraints. Now a zero budget
    means every candidate is marked "unknown" (metadata lookup budget exceeded) rather
    than silently accepted via a same-key cache entry."""
    activate_constraints_from_prompt("songs released in 2026 only")

    monkeypatch.setenv("METADATA_VALIDATION_MAX_LOOKUPS", "0")

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("a zero lookup budget must not trigger a network lookup")

    monkeypatch.setattr("backend.youtube.validate_candidate", fail_if_called)

    accepted, rejected = asyncio.run(
        _metadata_filter([{"artist": "Some Artist", "title": "Some Song"}])
    )

    assert accepted == []
    assert len(rejected) == 1
    assert rejected[0]["metadata_validation"]["status"] == "unknown"


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


def test_recco_deterministic_fallback_still_obeys_active_country_constraint(monkeypatch):
    activate_constraints(MetadataConstraints(artist_country="IT"))
    draft = deterministic_reccobeats_draft(
        [
            {
                "artist": "Italian Artist",
                "title": "Italian Song",
                "source": "reccobeats",
                "reccobeats_id": "it-1",
                "popularity": 70,
            },
            {
                "artist": "Foreign Artist",
                "title": "Foreign Song",
                "source": "reccobeats",
                "reccobeats_id": "us-1",
                "popularity": 80,
            },
        ],
        count=2,
    )
    assert draft is not None

    async def fake_validate(candidate, constraints, client=None):
        country = "IT" if candidate["artist"] == "Italian Artist" else "US"
        metadata = TrackMetadata(
            artist=candidate["artist"],
            title=candidate["title"],
            artist_country=country,
            match_score=0.96,
            confidence="high",
        )
        return validate_metadata(metadata, constraints)

    monkeypatch.setattr("backend.youtube.validate_candidate", fake_validate)

    accepted, rejected = asyncio.run(_metadata_filter(draft["tracks"]))

    assert [candidate["artist"] for candidate in accepted] == ["Italian Artist"]
    assert [candidate["artist"] for candidate in rejected] == ["Foreign Artist"]
    assert rejected[0]["metadata_validation"]["status"] == "invalid"
    assert "artist country US does not match IT" in rejected[0]["metadata_validation"]["violations"]


def test_replacement_prompt_shape_preserves_metadata_constraints():
    constraints = activate_constraints_from_prompt(
        "Suggest replacements. Original playlist request: Italian artists from 2026 only."
    )

    assert constraints == MetadataConstraints(release_year=2026, artist_country="IT")