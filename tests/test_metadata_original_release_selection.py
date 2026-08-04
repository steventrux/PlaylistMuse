from backend.metadata_validation import (
    MetadataConstraints,
    _metadata_from_recording,
    _select_best_metadata,
    validate_metadata,
)


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


def test_compilation_date_cannot_replace_original_release_year():
    compilation = _metadata_from_recording(
        _recording(
            recording_id="compilation-recording",
            artist="Survivor",
            title="Eye of the Tiger",
            api_score=100,
            release_title="Ces années-là : 1976/1985",
            release_date="1993-02-09",
        ),
        "Survivor",
        "Eye of the Tiger",
    )
    original = _metadata_from_recording(
        _recording(
            recording_id="original-recording",
            artist="Survivor",
            title="Eye of the Tiger",
            api_score=35,
            release_title="Eye of the Tiger",
            release_date="1982-05-29",
        ),
        "Survivor",
        "Eye of the Tiger",
    )

    selected = _select_best_metadata([compilation, original])

    assert selected.recording_mbid == "original-recording"
    assert selected.original_release_year == 1982
    result = validate_metadata(
        selected,
        MetadataConstraints(
            release_year_from=1986,
            release_year_to=1999,
        ),
    )
    assert result.status == "invalid"


def test_reissue_remains_valid_when_original_year_is_in_range():
    reissue = _metadata_from_recording(
        _recording(
            recording_id="reissue-recording",
            artist="Example Artist",
            title="Example Song",
            api_score=100,
            release_title="Example Song (2020 Remaster)",
            release_date="2020-06-01",
        ),
        "Example Artist",
        "Example Song",
    )
    original = _metadata_from_recording(
        _recording(
            recording_id="original-recording",
            artist="Example Artist",
            title="Example Song",
            api_score=40,
            release_title="Example Album",
            release_date="1988-03-12",
        ),
        "Example Artist",
        "Example Song",
    )

    selected = _select_best_metadata([reissue, original])

    assert selected.original_release_year == 1988
    result = validate_metadata(
        selected,
        MetadataConstraints(
            release_year_from=1986,
            release_year_to=1999,
        ),
    )
    assert result.status == "valid"
