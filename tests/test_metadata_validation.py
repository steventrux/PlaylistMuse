from pathlib import Path

from backend.metadata_validation import (
    MetadataConstraints,
    TrackMetadata,
    _album_matches,
    _metadata_from_recording,
    _read_cache,
    _write_cache,
    constraints_from_payload,
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


def test_extracts_explicit_year_range_and_named_decade():
    explicit = extract_metadata_constraints("Solo brani pubblicati dal 1990 al 1999")
    decade = extract_metadata_constraints("Rock anni ’90")
    assert (explicit.release_year_from, explicit.release_year_to) == (1990, 1999)
    assert (decade.release_year_from, decade.release_year_to) == (1990, 1999)


def test_extracts_direct_artist_but_not_similarity_reference():
    direct = extract_metadata_constraints("Musica dei Metallica per allenarsi")
    similar = extract_metadata_constraints("Musica come i Metallica per allenarsi")
    assert direct.allowed_artists == ["Metallica"]
    assert direct.active is True
    assert similar.allowed_artists == []
    assert similar.active is False


def test_similarity_decade_is_not_a_hard_filter():
    constraints = extract_metadata_constraints("Musica simile anni '90")
    assert constraints.release_year_from is None
    assert constraints.release_year_to is None
    assert constraints.active is False


def test_extracts_quoted_album_but_not_inspiration():
    direct = extract_metadata_constraints(
        'Crea una playlist solo con brani dall\'album "Rumours"'
    )
    inspired = extract_metadata_constraints("Una playlist ispirata a Rumours")
    assert direct.allowed_albums == ["Rumours"]
    assert inspired.allowed_albums == []


def test_multilingual_payload_supports_lists_exclusions_and_open_ranges():
    constraints = constraints_from_payload(
        {
            "allowed_artists": ["Metallica", "Megadeth"],
            "excluded_artists": ["Nirvana"],
            "allowed_albums": [],
            "excluded_albums": ["Load"],
            "release_year": None,
            "release_year_from": 1995,
            "release_year_to": None,
            "artist_country": None,
            "confidence": "high",
        }
    )
    assert constraints.allowed_artists == ["Metallica", "Megadeth"]
    assert constraints.excluded_artists == ["Nirvana"]
    assert constraints.excluded_albums == ["Load"]
    assert constraints.release_year_from == 1995


def test_low_confidence_interpretation_keeps_effective_local_fallback():
    fallback = MetadataConstraints(release_year_from=1990, release_year_to=1999)
    constraints = constraints_from_payload(
        {"allowed_artists": ["Wrong"], "confidence": "low"},
        fallback=fallback,
    )
    assert constraints.release_year_from == fallback.release_year_from
    assert constraints.release_year_to == fallback.release_year_to
    assert constraints.allowed_artists == fallback.allowed_artists
    assert constraints.excluded_artists == fallback.excluded_artists
    assert constraints.allowed_albums == fallback.allowed_albums
    assert constraints.excluded_albums == fallback.excluded_albums
    assert constraints.field_confidence
    assert all(value == 0.0 for value in constraints.field_confidence.values())


def test_validates_original_year_collaboration_and_album_edition():
    metadata = TrackMetadata(
        artist="Metallica feat. Marianne Faithfull",
        title="The Memory Remains",
        original_release_year=1997,
        matched_artist="Metallica feat. Marianne Faithfull",
        release_titles=["Reload (Remastered Deluxe Edition)"],
        match_score=0.97,
        confidence="high",
    )
    result = validate_metadata(
        metadata,
        MetadataConstraints(
            release_year_from=1990,
            release_year_to=1999,
            allowed_artists=["Metallica"],
            allowed_albums=["Reload"],
        ),
    )
    assert result.status == "valid"


def test_multiple_allowed_artists_are_alternatives():
    metadata = TrackMetadata(
        artist="Megadeth",
        title="Symphony of Destruction",
        original_release_year=1992,
        matched_artist="Megadeth",
        match_score=0.97,
        confidence="high",
    )
    result = validate_metadata(
        metadata,
        MetadataConstraints(allowed_artists=["Metallica", "Megadeth"]),
    )
    assert result.status == "valid"


def test_rejects_excluded_artist_album_and_outside_range():
    metadata = TrackMetadata(
        artist="Nirvana",
        title="Example Song",
        original_release_year=2004,
        matched_artist="Nirvana",
        release_titles=["Load"],
        match_score=0.95,
        confidence="high",
    )
    result = validate_metadata(
        metadata,
        MetadataConstraints(
            release_year_to=1999,
            excluded_artists=["Nirvana"],
            excluded_albums=["Load"],
        ),
    )
    assert result.status == "invalid"
    assert "release year 2004 is after 1999" in result.violations
    assert "artist Nirvana is excluded" in result.violations
    assert "track is listed on excluded album Load" in result.violations


def test_short_album_names_do_not_match_unrelated_prefixes():
    assert _album_matches("Load (Remastered)", "Load") is True
    assert _album_matches("Reload", "Load") is False


def test_unknown_when_required_album_metadata_is_missing():
    metadata = TrackMetadata(
        artist="Example",
        title="Unknown Album Song",
        original_release_year=2026,
        matched_artist="Example",
        match_score=0.95,
        confidence="high",
    )
    result = validate_metadata(
        metadata,
        MetadataConstraints(allowed_albums=["Target Album"]),
    )
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


def test_release_group_date_prevents_reissue_year_drift():
    metadata = _metadata_from_recording(
        {
            "id": "crazy-train-recording",
            "title": "Crazy Train",
            "score": 100,
            "artist-credit": [
                {
                    "name": "Ozzy Osbourne",
                    "artist": {"name": "Ozzy Osbourne", "country": "GB"},
                }
            ],
            "releases": [
                {
                    "title": "Blizzard of Ozz (40th Anniversary Expanded Edition)",
                    "date": "2021-09-17",
                    "release-group": {
                        "id": "blizzard-of-ozz",
                        "title": "Blizzard of Ozz",
                        "first-release-date": "1980-09-20",
                    },
                }
            ],
        },
        "Ozzy Osbourne",
        "Crazy Train",
    )

    assert metadata.original_release_date == "1980-09-20"
    assert metadata.original_release_year == 1980

    result = validate_metadata(
        metadata,
        MetadataConstraints(release_year_from=1986, release_year_to=1999),
    )
    assert result.status == "invalid"
    assert "release year 1980 is before 1986" in result.violations


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
    assert restored.release_titles == ["Cached Album"]
