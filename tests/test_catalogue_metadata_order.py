from __future__ import annotations

import asyncio

import pytest

from backend import youtube
from backend.metadata_validation import (
    MetadataConstraints,
    TrackMetadata,
    ValidationResult,
    activate_constraints,
)


EXCLUSIONS = {
    "exclude_live": True,
    "exclude_covers": True,
    "exclude_remixes": False,
}


@pytest.fixture(autouse=True)
def reset_constraints():
    activate_constraints(MetadataConstraints())
    yield
    activate_constraints(MetadataConstraints())


def _catalogue_track() -> dict[str, object]:
    return {
        "video_id": "canonical-video",
        "title": "Canonical Song",
        "artists": "Canonical Artist",
        "album": "Canonical Album",
        "duration": "3:30",
        "thumbnail_url": None,
        "url": "https://music.youtube.com/watch?v=canonical-video",
        "description": "Description.",
        "reason": "Reason.",
    }


def test_metadata_validation_uses_resolved_youtube_identity(monkeypatch) -> None:
    activate_constraints(
        MetadataConstraints(release_year_from=2000, release_year_to=2026)
    )
    seen: list[tuple[str, str]] = []

    monkeypatch.setattr(
        youtube,
        "_resolve_one",
        lambda candidate, exclusions: _catalogue_track(),
    )
    monkeypatch.setattr(youtube, "_read_cache", lambda *args, **kwargs: None)

    async def validate_canonical(candidate, constraints, client=None):
        seen.append((candidate["artist"], candidate["title"]))
        return ValidationResult(
            status="valid",
            violations=[],
            metadata=TrackMetadata(
                artist=candidate["artist"],
                title=candidate["title"],
                original_release_year=2023,
                matched_artist=candidate["artist"],
                match_score=0.98,
                confidence="high",
            ),
        )

    monkeypatch.setattr(youtube, "validate_candidate", validate_canonical)

    resolved, unresolved = asyncio.run(
        youtube.resolve_candidates(
            [{"artist": "AI Artist Alias", "title": "AI Song Alias"}],
            EXCLUSIONS,
        )
    )

    assert seen == [("Canonical Artist", "Canonical Song")]
    assert unresolved == []
    assert len(resolved) == 1
    assert resolved[0]["title"] == "Canonical Song"
    assert resolved[0]["artists"] == "Canonical Artist"
    assert resolved[0]["metadata_validation"]["original_release_year"] == 2023


def test_unknown_canonical_metadata_remains_rejected(monkeypatch) -> None:
    activate_constraints(
        MetadataConstraints(release_year_from=2000, release_year_to=2026)
    )

    monkeypatch.setattr(
        youtube,
        "_resolve_one",
        lambda candidate, exclusions: _catalogue_track(),
    )
    monkeypatch.setattr(youtube, "_read_cache", lambda *args, **kwargs: None)

    async def unknown_metadata(candidate, constraints, client=None):
        return ValidationResult(
            status="unknown",
            violations=[],
            metadata=TrackMetadata(
                artist=candidate["artist"],
                title=candidate["title"],
                warnings=["No MusicBrainz match"],
            ),
        )

    monkeypatch.setattr(youtube, "validate_candidate", unknown_metadata)

    resolved, unresolved = asyncio.run(
        youtube.resolve_candidates(
            [{"artist": "AI Artist Alias", "title": "AI Song Alias"}],
            EXCLUSIONS,
        )
    )

    assert resolved == []
    assert len(unresolved) == 1
    assert unresolved[0]["artist"] == "AI Artist Alias"
    assert unresolved[0]["title"] == "AI Song Alias"
    assert unresolved[0]["unresolved_reason"] == "metadata_validation"
    assert unresolved[0]["metadata_validation"]["status"] == "unknown"
    assert unresolved[0]["resolved_catalogue"] == {
        "title": "Canonical Song",
        "artists": "Canonical Artist",
        "video_id": "canonical-video",
    }
