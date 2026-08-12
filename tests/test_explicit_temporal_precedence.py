from datetime import UTC, datetime

from backend.metadata_validation import (
    TrackMetadata,
    constraints_from_payload,
    extract_metadata_constraints,
    validate_metadata,
)


def test_explicit_temporal_range_cannot_be_broadened_by_ai() -> None:
    prompt = (
        "Crea una playlist rock di brani degli anni ’80 oppure degli anni ’90, "
        "ma solo pubblicati dopo il 1985."
    )
    fallback = extract_metadata_constraints(prompt)
    constraints = constraints_from_payload(
        {
            "release_year_from": 1980,
            "release_year_to": 1999,
            "field_confidence": {
                "release_year_from": 0.99,
                "release_year_to": 0.99,
            },
        },
        fallback=fallback,
    )

    assert (fallback.release_year_from, fallback.release_year_to) == (1986, 1999)
    assert (constraints.release_year_from, constraints.release_year_to) == (
        1986,
        1999,
    )

    result = validate_metadata(
        TrackMetadata(
            artist="Survivor",
            title="Eye of the Tiger",
            original_release_year=1982,
            matched_artist="Survivor",
            match_score=0.98,
            confidence="high",
        ),
        constraints,
    )

    assert result.status == "invalid"
    assert "release year 1982 is before 1986" in result.violations


def test_ai_temporal_range_is_used_when_prompt_has_no_local_range() -> None:
    constraints = constraints_from_payload(
        {
            "release_year_from": 2000,
            "release_year_to": 2009,
            "field_confidence": {
                "release_year_from": 0.99,
                "release_year_to": 0.99,
            },
        }
    )

    assert (constraints.release_year_from, constraints.release_year_to) == (
        2000,
        2009,
    )


def test_local_year_to_present_range_overrides_ai_exact_year_misread() -> None:
    prompt = (
        "Crea una playlist di musica italiana dal 2000 ad oggi adatta per un party. "
        "il mood deve essere festoso."
    )
    current_year = datetime.now(UTC).year
    fallback = extract_metadata_constraints(prompt)

    constraints = constraints_from_payload(
        {
            "release_year": 2000,
            "release_year_from": None,
            "release_year_to": None,
            "field_confidence": {
                "release_year": 0.99,
                "release_year_from": 0.0,
                "release_year_to": 0.0,
            },
        },
        fallback=fallback,
    )

    assert fallback.release_year is None
    assert (fallback.release_year_from, fallback.release_year_to) == (
        2000,
        current_year,
    )
    assert constraints.release_year is None
    assert (constraints.release_year_from, constraints.release_year_to) == (
        2000,
        current_year,
    )

    result = validate_metadata(
        TrackMetadata(
            artist="Example Artist",
            title="Example Track",
            original_release_year=2023,
            matched_artist="Example Artist",
            match_score=0.98,
            confidence="high",
        ),
        constraints,
    )

    assert result.status == "valid"
