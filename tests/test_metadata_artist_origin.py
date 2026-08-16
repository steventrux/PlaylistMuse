import asyncio

from backend import metadata_validation
from backend.metadata_validation import (
    MetadataConstraints,
    TrackMetadata,
    _metadata_from_recording,
    validate_candidate,
)
from backend.musicbrainz_artist import ArtistOrigin


def test_recording_metadata_preserves_primary_artist_mbid():
    metadata = _metadata_from_recording(
        {
            "id": "recording-id",
            "title": "Song",
            "score": 100,
            "artist-credit": [
                {
                    "name": "Måneskin",
                    "artist": {
                        "id": "artist-mbid",
                        "name": "Måneskin",
                    },
                }
            ],
            "releases": [
                {
                    "title": "Album",
                    "date": "2021-01-01",
                    "release-group": {
                        "id": "release-group-id",
                        "title": "Album",
                        "first-release-date": "2021-01-01",
                    },
                }
            ],
        },
        "Måneskin",
        "Song",
    )

    assert metadata.artist_mbid == "artist-mbid"
    assert metadata.artist_country is None


def test_validate_candidate_enriches_missing_country_from_artist_mbid(monkeypatch):
    metadata = TrackMetadata(
        artist="Måneskin",
        title="Song",
        recording_mbid="recording-id",
        artist_mbid="artist-mbid",
        original_release_year=2021,
        matched_artist="Måneskin",
        match_score=0.99,
        confidence="high",
    )
    lookup_calls = 0

    async def fake_track_lookup(*args, **kwargs):
        return metadata

    async def fake_origin_lookup(artist_mbid, *, client=None):
        nonlocal lookup_calls
        lookup_calls += 1
        assert artist_mbid == "artist-mbid"
        return ArtistOrigin(country="IT", area="Rome")

    monkeypatch.setattr(metadata_validation, "lookup_track_metadata", fake_track_lookup)
    monkeypatch.setattr(metadata_validation, "lookup_artist_origin", fake_origin_lookup)
    monkeypatch.setattr(metadata_validation, "_write_cache", lambda *args, **kwargs: None)

    result = asyncio.run(
        validate_candidate(
            {"artist": "Måneskin", "title": "Song"},
            MetadataConstraints(artist_country="IT"),
        )
    )

    assert result.status == "valid"
    assert result.metadata.artist_country == "IT"
    assert result.metadata.artist_area == "Rome"
    assert lookup_calls == 1


def test_validate_candidate_rejects_foreign_country_resolved_by_artist_mbid(monkeypatch):
    metadata = TrackMetadata(
        artist="Foreign Artist",
        title="Song",
        recording_mbid="recording-id",
        artist_mbid="artist-mbid",
        original_release_year=2021,
        matched_artist="Foreign Artist",
        match_score=0.99,
        confidence="high",
    )

    async def fake_track_lookup(*args, **kwargs):
        return metadata

    async def fake_origin_lookup(artist_mbid, *, client=None):
        return ArtistOrigin(country="US", area="New York")

    monkeypatch.setattr(metadata_validation, "lookup_track_metadata", fake_track_lookup)
    monkeypatch.setattr(metadata_validation, "lookup_artist_origin", fake_origin_lookup)
    monkeypatch.setattr(metadata_validation, "_write_cache", lambda *args, **kwargs: None)

    result = asyncio.run(
        validate_candidate(
            {"artist": "Foreign Artist", "title": "Song"},
            MetadataConstraints(artist_country="IT"),
        )
    )

    assert result.status == "invalid"
    assert "artist country US does not match IT" in result.violations


def test_validate_candidate_does_not_lookup_origin_without_country_constraint(monkeypatch):
    metadata = TrackMetadata(
        artist="Artist",
        title="Song",
        artist_mbid="artist-mbid",
        original_release_year=2021,
        matched_artist="Artist",
        match_score=0.99,
        confidence="high",
    )

    async def fake_track_lookup(*args, **kwargs):
        return metadata

    async def fail_origin_lookup(*args, **kwargs):
        raise AssertionError("artist origin must not be fetched without a country constraint")

    monkeypatch.setattr(metadata_validation, "lookup_track_metadata", fake_track_lookup)
    monkeypatch.setattr(metadata_validation, "lookup_artist_origin", fail_origin_lookup)

    result = asyncio.run(
        validate_candidate(
            {"artist": "Artist", "title": "Song"},
            MetadataConstraints(release_year_from=2000),
        )
    )

    assert result.status == "valid"
