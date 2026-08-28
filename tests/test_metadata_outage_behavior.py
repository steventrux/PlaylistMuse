import asyncio

import pytest

from backend.metadata_runtime import MetadataServiceUnavailableError
from backend.youtube import _metadata_filter as metadata_filter
from backend.metadata_validation import (
    TrackMetadata,
    ValidationResult,
    activate_constraints_from_prompt,
)


@pytest.fixture(autouse=True)
def reset_metadata_constraints():
    activate_constraints_from_prompt("generic playlist")
    yield
    activate_constraints_from_prompt("generic playlist")


def _unknown_result(candidate, warning):
    return ValidationResult(
        status="unknown",
        violations=[],
        metadata=TrackMetadata(
            artist=candidate["artist"],
            title=candidate["title"],
            match_score=0.0,
            confidence="low",
            warnings=[warning],
        ),
    )


def test_complete_musicbrainz_outage_raises_temporary_service_error(monkeypatch):
    activate_constraints_from_prompt("songs released in 2026 only")

    async def unavailable(candidate, constraints, client=None):
        return _unknown_result(
            candidate,
            "Metadata lookup unavailable: ConnectTimeout",
        )

    monkeypatch.setattr("backend.youtube.validate_candidate", unavailable)

    with pytest.raises(
        MetadataServiceUnavailableError,
        match="temporarily unavailable",
    ):
        asyncio.run(
            metadata_filter(
                [
                    {"artist": "Artist A", "title": "Song A"},
                    {"artist": "Artist B", "title": "Song B"},
                ]
            )
        )


def test_severe_partial_outage_raises_without_waiting_for_total_failure(monkeypatch):
    """A round where MusicBrainz fails on the overwhelming majority of lookups (but
    happens to let one through) must still trip the circuit breaker -- this mirrors
    the real incident where round 1 had 21/22 temporary failures (95%) yet the old
    exact-100% check let three more expensive replenishment rounds run before the
    ratio eventually hit exactly 100% by chance."""
    activate_constraints_from_prompt("songs released in 2026 only")

    async def mostly_unavailable(candidate, constraints, client=None):
        if candidate["title"] == "Lucky":
            return ValidationResult(
                status="valid",
                violations=[],
                metadata=TrackMetadata(
                    artist=candidate["artist"],
                    title=candidate["title"],
                    original_release_year=2026,
                    match_score=0.97,
                    confidence="high",
                ),
            )
        return _unknown_result(
            candidate,
            "Metadata lookup unavailable: ReadTimeout",
        )

    monkeypatch.setattr("backend.youtube.validate_candidate", mostly_unavailable)

    candidates = [{"artist": "Artist A", "title": "Lucky"}] + [
        {"artist": f"Artist {i}", "title": f"Unavailable {i}"} for i in range(8)
    ]

    with pytest.raises(
        MetadataServiceUnavailableError,
        match="temporarily unavailable",
    ):
        asyncio.run(metadata_filter(candidates))


def test_genuine_unknown_metadata_remains_a_rejection(monkeypatch):
    activate_constraints_from_prompt("songs released in 2026 only")

    async def no_match(candidate, constraints, client=None):
        return _unknown_result(candidate, "No MusicBrainz match")

    monkeypatch.setattr("backend.youtube.validate_candidate", no_match)

    accepted, rejected = asyncio.run(
        metadata_filter([{"artist": "Artist", "title": "Unknown Song"}])
    )

    assert accepted == []
    assert len(rejected) == 1
    assert rejected[0]["unresolved_reason"] == "metadata_validation"
    assert rejected[0]["metadata_validation"]["status"] == "unknown"


def test_partial_outage_keeps_verified_results_and_marks_failed_lookup(monkeypatch):
    activate_constraints_from_prompt("songs released in 2026 only")

    async def mixed_result(candidate, constraints, client=None):
        if candidate["title"] == "Verified":
            return ValidationResult(
                status="valid",
                violations=[],
                metadata=TrackMetadata(
                    artist=candidate["artist"],
                    title=candidate["title"],
                    original_release_year=2026,
                    match_score=0.97,
                    confidence="high",
                ),
            )
        return _unknown_result(
            candidate,
            "Metadata lookup unavailable: ReadTimeout",
        )

    monkeypatch.setattr("backend.youtube.validate_candidate", mixed_result)

    accepted, rejected = asyncio.run(
        metadata_filter(
            [
                {"artist": "Artist A", "title": "Verified"},
                {"artist": "Artist B", "title": "Unavailable"},
            ]
        )
    )

    assert [candidate["title"] for candidate in accepted] == ["Verified"]
    assert len(rejected) == 1
    assert rejected[0]["title"] == "Unavailable"
    assert rejected[0]["unresolved_reason"] == "metadata_service_unavailable"
