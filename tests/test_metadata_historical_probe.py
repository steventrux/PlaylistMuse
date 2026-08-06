import asyncio

import backend.metadata_validation as metadata_validation
from backend.metadata_validation import (
    MetadataConstraints,
    TrackMetadata,
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
