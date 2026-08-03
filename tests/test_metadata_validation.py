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


def test_extracts_explicit_year_range():
    constraints = extract_metadata_constraints(
        "Solo brani pubblicati dal 1990 al 1999"
    )

    assert constraints.release_year is None
    assert constraints.release_year_from == 1990
    assert constraints.release_year_to == 1999
    assert constraints.active is True


def test_extracts_named_decade_as_hard_constraint():
    constraints = extract_metadata_constraints("Rock anni ’90")

    assert constraints.release_year is None
    assert constraints.release_year_from == 1990
    assert constraints.release_year_to == 1999
    assert constraints.active is True


def test_extracts_direct_artist_ownership_as_hard_constraint():
    constraints = extract_metadata_constraints("Musica dei Metallica per allenarsi")

    assert constraints.artist_name == "Metallica"
    assert constraints.active is True


def test_extracts_exact_artist_when_explicitly_quoted():
    constraints = extract_metadata_constraints('Only songs by "Metallica"')

    assert constraints.artist_name == "Metallica"
    assert constraints.active is True


def test_similarity_language_does_not_create_artist_or_decade_filters():
    artist_prompt = extract_metadata_constraints(
        "Musica come i Metallica per allenarsi"
    )
    decade_prompt = extract_metadata_constraints("Musica simile anni '90")

    assert artist_prompt.artist_name is None
    assert artist_prompt.active is False
    assert decade_prompt.release_year_from is None
    assert decade_prompt.release_year_to is None
    assert decade_prompt.active is False


def test_extracts_quoted_album_constraint():
    constraints = extract_metadata_constraints(
        'Crea una playlist solo con brani dall\'album "Rumours"'
    )

    assert constraints.album_name == "Rumours"
    assert constraints.active is True


def test_generic_prompt_has_no_metadata_constraints():
    constraints = extract_metadata_constraints("Relaxing music for a journey on the road")

    assert constraints.release_year is None
    assert constraints.release_year_from is None
    assert constraints.release_year_to is None
    assert constraints.artist_country is None
    assert constraints.artist_name is None
    assert constraints.album_name is None
    assert constraints.active is False


def test_inspired_album_mention_is_not_a_hard_filter():
    constraints = extract_metadata_constraints("Una playlist ispirata a Rumours")

    assert constraints.album_name is None
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


def test_validates_matching_range_artist_and_album():
    metadata = TrackMetadata(
        artist="Fleetwood Mac",
        title="The Chain",
        original_release_year=1977,
        matched_artist="Fleetwood Mac",
        release_titles=["Rumours", "The Very Best of Fleetwood Mac"],
        match_score=0.97,
        confidence="high",
    )

    result = validate_metadata(
        metadata,
        MetadataConstraints(
            release_year_from=1970,
            release_year_to=1979,
            artist_name="Fleetwood Mac",
            album_name="Rumours",
        ),
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


def test_rejects_outside_range_wrong_artist_and_album():
    metadata = TrackMetadata(
        artist="Example",
        title="Example Song",
        original_release_year=2004,
        matched_artist="Example",
        release_titles=["Another Album"],
        match_score=0.95,
        confidence="high",
    )

    result = validate_metadata(
        metadata,
        MetadataConstraints(
            release_year_from=1990,
            release_year_to=1999,
            artist_name="Metallica",
            album_name="Load",
        ),
    )

    assert result.status == "invalid"
    assert "release year 2004 is outside 1990-1999" in result.violations
    assert "artist Example does not match Metallica" in result.violations
    assert "track is not listed on album Load" in result.violations


def test_unknown_when_required_album_metadata_is_missing():
    metadata = TrackMetadata(
        artist="Example",
        title="Unknown Album Song",
        original_release_year=2026,
        matched_artist="Example",
        match_score=0.95,
        confidence="high",
    )

    result = validate_metadata(metadata, MetadataConstraints(album_name="Target Album"))

    assert result.status == "unknown"


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
        matched_artist="Cached Artist",
        release_titles=["Cached Album"],
        match_score=0.94,
        confidence="high",
    )

    _write_cache(metadata, ttl=60, path=cache)
    restored = _read_cache("Cached Artist", "Cached Song", path=cache)

    assert restored is not None
    assert restored.recording_mbid == "recording-id"
    assert restored.original_release_year == 2026
    assert restored.artist_country == "IT"
    assert restored.matched_artist == "Cached Artist"
    assert restored.release_titles == ["Cached Album"]
