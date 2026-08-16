import asyncio

import backend.metadata_validation as metadata_validation
from backend.metadata_validation import (
    MetadataConstraints,
    TrackMetadata,
    _strip_title_edition_suffix,
    validate_candidate,
)


class StubResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _recording(
    *,
    recording_id: str,
    artist: str,
    title: str,
    api_score: int,
    release_title: str,
    release_date: str,
) -> dict:
    return {
        "id": recording_id,
        "title": title,
        "score": api_score,
        "artist-credit": [
            {
                "name": artist,
                "artist": {"name": artist},
            }
        ],
        "releases": [
            {
                "title": release_title,
                "date": release_date,
                "release-group": {
                    "id": f"{recording_id}-group",
                    "title": release_title,
                    "first-release-date": release_date,
                },
            }
        ],
    }


def test_historical_probe_rejects_compilation_date_false_positive(
    monkeypatch,
    tmp_path,
):
    initial = TrackMetadata(
        artist="Survivor",
        title="Eye of the Tiger",
        recording_mbid="compilation-recording",
        original_release_date="1993-02-09",
        original_release_year=1993,
        matched_artist="Survivor",
        release_titles=["Ces années-là : 1976/1985"],
        match_score=1.0,
        confidence="high",
    )

    async def fake_lookup(*args, **kwargs):
        return initial

    async def fake_get(client, params):
        assert "firstreleasedate:[* TO 1999-12-31]" in params["query"]
        return StubResponse(
            {
                "recordings": [
                    _recording(
                        recording_id="original-recording",
                        artist="Survivor",
                        title="Eye of the Tiger",
                        api_score=35,
                        release_title="Eye of the Tiger",
                        release_date="1982-05-29",
                    )
                ]
            }
        )

    monkeypatch.setattr(
        metadata_validation,
        "lookup_track_metadata",
        fake_lookup,
    )
    monkeypatch.setattr(
        metadata_validation,
        "_rate_limited_get",
        fake_get,
    )

    result = asyncio.run(
        validate_candidate(
            {"artist": "Survivor", "title": "Eye of the Tiger"},
            MetadataConstraints(
                release_year_from=1986,
                release_year_to=1999,
            ),
            cache_path=tmp_path / "metadata.sqlite3",
        )
    )

    assert result.status == "invalid"
    assert result.metadata.original_release_year == 1982
    assert "release year 1982 is before 1986" in result.violations


def test_historical_probe_keeps_reissue_when_original_is_in_range(
    monkeypatch,
    tmp_path,
):
    initial = TrackMetadata(
        artist="Example Artist",
        title="Example Song",
        recording_mbid="reissue-recording",
        original_release_date="2020-06-01",
        original_release_year=2020,
        matched_artist="Example Artist",
        release_titles=["Example Song (2020 Remaster)"],
        match_score=1.0,
        confidence="high",
    )

    async def fake_lookup(*args, **kwargs):
        return initial

    async def fake_get(client, params):
        assert "firstreleasedate:[* TO 1999-12-31]" in params["query"]
        return StubResponse(
            {
                "recordings": [
                    _recording(
                        recording_id="original-recording",
                        artist="Example Artist",
                        title="Example Song",
                        api_score=40,
                        release_title="Example Album",
                        release_date="1988-03-12",
                    )
                ]
            }
        )

    monkeypatch.setattr(
        metadata_validation,
        "lookup_track_metadata",
        fake_lookup,
    )
    monkeypatch.setattr(
        metadata_validation,
        "_rate_limited_get",
        fake_get,
    )

    result = asyncio.run(
        validate_candidate(
            {"artist": "Example Artist", "title": "Example Song"},
            MetadataConstraints(
                release_year_from=1986,
                release_year_to=1999,
            ),
            cache_path=tmp_path / "metadata.sqlite3",
        )
    )

    assert result.status == "valid"
    assert result.metadata.original_release_year == 1988


def test_confident_original_album_in_range_skips_the_historical_probe(
    monkeypatch,
    tmp_path,
):
    """A clean, high-confidence album match must not pay for a second MusicBrainz call."""
    initial = TrackMetadata(
        artist="Metallica",
        title="Sad But True",
        recording_mbid="original-recording",
        original_release_date="1991-08-12",
        original_release_year=1991,
        matched_artist="Metallica",
        release_titles=["Metallica"],
        release_group_primary_type="Album",
        release_group_secondary_types=(),
        match_score=0.95,
        confidence="high",
    )

    async def fake_lookup(*args, **kwargs):
        return initial

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("the historical probe should have been skipped")

    monkeypatch.setattr(metadata_validation, "lookup_track_metadata", fake_lookup)
    monkeypatch.setattr(metadata_validation, "_rate_limited_get", fail_if_called)

    result = asyncio.run(
        validate_candidate(
            {"artist": "Metallica", "title": "Sad But True"},
            MetadataConstraints(release_year_from=1986, release_year_to=1999),
            cache_path=tmp_path / "metadata.sqlite3",
        )
    )

    assert result.status == "valid"
    assert result.metadata.original_release_year == 1991


def test_confident_original_album_at_exact_year_skips_the_historical_probe(
    monkeypatch,
    tmp_path,
):
    initial = TrackMetadata(
        artist="Metallica",
        title="Sad But True",
        recording_mbid="original-recording",
        original_release_date="1991-08-12",
        original_release_year=1991,
        matched_artist="Metallica",
        release_titles=["Metallica"],
        release_group_primary_type="Album",
        release_group_secondary_types=(),
        match_score=0.95,
        confidence="high",
    )

    async def fake_lookup(*args, **kwargs):
        return initial

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("the historical probe should have been skipped")

    monkeypatch.setattr(metadata_validation, "lookup_track_metadata", fake_lookup)
    monkeypatch.setattr(metadata_validation, "_rate_limited_get", fail_if_called)

    result = asyncio.run(
        validate_candidate(
            {"artist": "Metallica", "title": "Sad But True"},
            MetadataConstraints(release_year=1991),
            cache_path=tmp_path / "metadata.sqlite3",
        )
    )

    assert result.status == "valid"


def test_compilation_secondary_type_still_triggers_the_historical_probe(
    monkeypatch,
    tmp_path,
):
    """A Compilation secondary-type must not be treated as a confident original release."""
    initial = TrackMetadata(
        artist="Survivor",
        title="Eye of the Tiger",
        recording_mbid="compilation-recording",
        original_release_date="1993-02-09",
        original_release_year=1993,
        matched_artist="Survivor",
        release_titles=["Ces années-là : 1976/1985"],
        release_group_primary_type="Album",
        release_group_secondary_types=("Compilation",),
        match_score=0.95,
        confidence="high",
    )

    probed = False

    async def fake_lookup(*args, **kwargs):
        return initial

    async def fake_get(client, params):
        nonlocal probed
        probed = True
        assert "firstreleasedate:[* TO 1999-12-31]" in params["query"]
        return StubResponse({"recordings": []})

    monkeypatch.setattr(metadata_validation, "lookup_track_metadata", fake_lookup)
    monkeypatch.setattr(metadata_validation, "_rate_limited_get", fake_get)

    asyncio.run(
        validate_candidate(
            {"artist": "Survivor", "title": "Eye of the Tiger"},
            MetadataConstraints(release_year_from=1986, release_year_to=1999),
            cache_path=tmp_path / "metadata.sqlite3",
        )
    )

    assert probed


def test_confident_original_single_skips_the_historical_probe(
    monkeypatch,
    tmp_path,
):
    """Single/EP release-groups are legitimate original releases, not just Album."""
    initial = TrackMetadata(
        artist="Van Halen",
        title="Jump",
        recording_mbid="original-recording",
        original_release_date="1983-12-27",
        original_release_year=1983,
        matched_artist="Van Halen",
        release_titles=["Jump"],
        release_group_primary_type="Single",
        release_group_secondary_types=(),
        match_score=0.95,
        confidence="high",
    )

    async def fake_lookup(*args, **kwargs):
        return initial

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("the historical probe should have been skipped")

    monkeypatch.setattr(metadata_validation, "lookup_track_metadata", fake_lookup)
    monkeypatch.setattr(metadata_validation, "_rate_limited_get", fail_if_called)

    result = asyncio.run(
        validate_candidate(
            {"artist": "Van Halen", "title": "Jump"},
            MetadataConstraints(release_year_from=1980, release_year_to=2005),
            cache_path=tmp_path / "metadata.sqlite3",
        )
    )

    assert result.status == "valid"


def test_broadcast_release_type_still_triggers_the_historical_probe(
    monkeypatch,
    tmp_path,
):
    """A release type outside Album/Single/EP (e.g. Broadcast) must still probe."""
    initial = TrackMetadata(
        artist="Metallica",
        title="Sad But True",
        recording_mbid="broadcast-recording",
        original_release_date="1989-01-01",
        original_release_year=1989,
        matched_artist="Metallica",
        release_titles=["Radio Broadcast"],
        release_group_primary_type="Broadcast",
        release_group_secondary_types=(),
        match_score=0.95,
        confidence="high",
    )

    probed = False

    async def fake_lookup(*args, **kwargs):
        return initial

    async def fake_get(client, params):
        nonlocal probed
        probed = True
        return StubResponse({"recordings": []})

    monkeypatch.setattr(metadata_validation, "lookup_track_metadata", fake_lookup)
    monkeypatch.setattr(metadata_validation, "_rate_limited_get", fake_get)

    asyncio.run(
        validate_candidate(
            {"artist": "Metallica", "title": "Sad But True"},
            MetadataConstraints(release_year_from=1986, release_year_to=1999),
            cache_path=tmp_path / "metadata.sqlite3",
        )
    )

    assert probed


def test_low_confidence_album_still_triggers_the_historical_probe(
    monkeypatch,
    tmp_path,
):
    """A clean Album type alone is not enough -- the match score must also be high."""
    initial = TrackMetadata(
        artist="Metallica",
        title="Sad But True",
        recording_mbid="original-recording",
        original_release_date="1991-08-12",
        original_release_year=1991,
        matched_artist="Metallica",
        release_titles=["Metallica"],
        release_group_primary_type="Album",
        release_group_secondary_types=(),
        match_score=0.85,
        confidence="medium",
    )

    probed = False

    async def fake_lookup(*args, **kwargs):
        return initial

    async def fake_get(client, params):
        nonlocal probed
        probed = True
        return StubResponse({"recordings": []})

    monkeypatch.setattr(metadata_validation, "lookup_track_metadata", fake_lookup)
    monkeypatch.setattr(metadata_validation, "_rate_limited_get", fake_get)

    asyncio.run(
        validate_candidate(
            {"artist": "Metallica", "title": "Sad But True"},
            MetadataConstraints(release_year_from=1986, release_year_to=1999),
            cache_path=tmp_path / "metadata.sqlite3",
        )
    )

    assert probed


def test_strip_title_edition_suffix_removes_common_edition_descriptors() -> None:
    assert _strip_title_edition_suffix("Summer of 69 (Classic Version)") == "Summer of 69"
    assert _strip_title_edition_suffix("Song (2011 Remastered)") == "Song"
    assert _strip_title_edition_suffix("Song (Live)") == "Song"
    assert _strip_title_edition_suffix("Song - Radio Edit") == "Song"
    assert _strip_title_edition_suffix("Song (Extended Version)") == "Song"


def test_strip_title_edition_suffix_leaves_plain_titles_unchanged() -> None:
    assert _strip_title_edition_suffix("Take on Me") == "Take on Me"
    assert _strip_title_edition_suffix("(Sittin' On) The Dock of the Bay") == (
        "(Sittin' On) The Dock of the Bay"
    )


def test_validate_candidate_searches_with_the_edition_suffix_stripped(monkeypatch) -> None:
    """The exact bug this fixes: a "(Classic Version)" upload must not be matched to a
    rerelease's date instead of the original song's true release year."""
    seen_titles: list[str] = []

    async def fake_lookup(artist, title, **kwargs):
        seen_titles.append(title)
        year = 1984 if title == "Summer of 69" else 2022
        return TrackMetadata(
            artist=artist,
            title=title,
            original_release_date=f"{year}-01-01",
            original_release_year=year,
            match_score=1.0,
            confidence="high",
        )

    monkeypatch.setattr(metadata_validation, "lookup_track_metadata", fake_lookup)

    result = asyncio.run(
        validate_candidate(
            {"artist": "Bryan Adams", "title": "Summer of 69 (Classic Version)"},
            MetadataConstraints(),
        )
    )

    assert seen_titles == ["Summer of 69"]
    assert result.metadata.original_release_year == 1984
