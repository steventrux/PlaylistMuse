from __future__ import annotations

import asyncio

from backend.metadata_validation import MetadataConstraints, TrackMetadata, ValidationResult
from backend.temporal_alias_guard import filter_temporal_artist_aliases


def _track() -> dict:
    return {
        "artists": "Current Artist /Legacy Group",
        "title": "Same Song",
        "requested_artist": "Current Artist",
        "requested_title": "Same Song",
        "video_id": "video-1",
        "metadata_validation": {
            "recording_mbid": "current-recording",
            "original_release_year": 2012,
        },
    }


def _result(artist: str, year: int, mbid: str, *, invalid: bool) -> ValidationResult:
    metadata = TrackMetadata(
        artist=artist,
        title="Same Song",
        recording_mbid=mbid,
        original_release_date=str(year),
        original_release_year=year,
        match_score=1.0,
        confidence="high",
        matched_artist=artist,
    )
    violations = ["release year 1992 is before 2000"] if invalid else []
    return ValidationResult("invalid" if invalid else "valid", violations, metadata)


def test_temporal_alias_rejects_only_when_same_work_is_confirmed(monkeypatch) -> None:
    async def fake_validate(candidate, constraints, client=None):
        if candidate["artist"] == "Legacy Group":
            return _result("Legacy Group", 1992, "old-recording", invalid=True)
        return _result(candidate["artist"], 2012, "current-recording", invalid=False)

    async def fake_work_ids(mbid, client=None):
        if mbid in {"current-recording", "old-recording"}:
            return frozenset({"shared-work"})
        return frozenset()

    monkeypatch.setattr("backend.temporal_alias_guard.validate_candidate", fake_validate)
    monkeypatch.setattr("backend.temporal_alias_guard.recording_work_ids", fake_work_ids)

    accepted, rejected = asyncio.run(
        filter_temporal_artist_aliases(
            [_track()],
            MetadataConstraints(release_year_from=2000, release_year_to=2026),
        )
    )

    assert accepted == []
    assert len(rejected) == 1
    assert rejected[0]["unresolved_reason"] == "metadata_validation"
    assert rejected[0]["metadata_validation"]["original_release_year"] == 1992


def test_temporal_alias_does_not_use_same_title_without_same_work(monkeypatch) -> None:
    async def fake_validate(candidate, constraints, client=None):
        if candidate["artist"] == "Legacy Group":
            return _result("Legacy Group", 1992, "old-recording", invalid=True)
        return _result(candidate["artist"], 2012, "current-recording", invalid=False)

    async def fake_work_ids(mbid, client=None):
        return {
            "current-recording": frozenset({"current-work"}),
            "old-recording": frozenset({"different-work"}),
        }.get(mbid, frozenset())

    monkeypatch.setattr("backend.temporal_alias_guard.validate_candidate", fake_validate)
    monkeypatch.setattr("backend.temporal_alias_guard.recording_work_ids", fake_work_ids)

    track = _track()
    accepted, rejected = asyncio.run(
        filter_temporal_artist_aliases(
            [track],
            MetadataConstraints(release_year_from=2000, release_year_to=2026),
        )
    )

    assert accepted == [track]
    assert rejected == []
