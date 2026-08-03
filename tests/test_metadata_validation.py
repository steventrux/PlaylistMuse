from pathlib import Path

from backend.metadata_validation import (
    MetadataConstraints,
    TrackMetadata,
    _read_cache,
    _write_cache,
    extract_metadata_constraints,
    validate_metadata,
)


def test_extracts_explicit_release_year_and_italian_artist_constraint():
    constraints = extract_metadata_constraints(
        "Solo hit del 2026 di artisti italiani per l'estate"
    )

    assert constraints.release_year == 2026
    assert constraints.artist_country == "IT"
    assert constraints.active is True


def test_generic_prompt_has_no_metadata_constraints():
    constraints = extract_metadata_constraints("Relaxing music for a journey on the road")

    assert constraints.release_year is None
    assert constraints.artist_country is None
    assert constraints.active is False


def test_validates_matching_year_and_country():
    metadata = TrackMetadata(
        artist="Example",
        title="Summer Song",
        original_release_year=2026,
        artist_country="IT",
        match_score=0.96,
        confidence="high",
    )

    result = validate_metadata(
        metadata,
        MetadataConstraints(release_year=2026, artist_country="IT"),
    )

    assert result.status == "valid"
    assert result.violations == []


def test_rejects_wrong_release_year():
    metadata = TrackMetadata(
        artist="Example",
        title="Old Song",
        original_release_year=2022,
        artist_country="IT",
        match_score=0.95,
        confidence="high",
    )

    result = validate_metadata(metadata, MetadataConstraints(release_year=2026))

    assert result.status == "invalid"
    assert "release year 2022 does not match 2026" in result.violations


def test_unknown_when_metadata_is_missing_or_match_is_weak():
    metadata = TrackMetadata(
        artist="Unknown",
        title="Unknown Song",
        match_score=0.45,
        confidence="low",
    )

    result = validate_metadata(
        metadata,
        MetadataConstraints(release_year=2026, artist_country="IT"),
    )

    assert result.status == "unknown"


def test_sqlite_cache_round_trip(tmp_path: Path):
    cache = tmp_path / "metadata.sqlite3"
    metadata = TrackMetadata(
        artist="Cached Artist",
        title="Cached Song",
        recording_mbid="recording-id",
        original_release_year=2026,
        artist_country="IT",
        match_score=0.94,
        confidence="high",
    )

    _write_cache(metadata, ttl=60, path=cache)
    restored = _read_cache("Cached Artist", "Cached Song", path=cache)

    assert restored is not None
    assert restored.recording_mbid == "recording-id"
    assert restored.original_release_year == 2026
    assert restored.artist_country == "IT"
