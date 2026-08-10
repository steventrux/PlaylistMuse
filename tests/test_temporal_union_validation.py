import pytest

from backend.metadata_validation import extract_metadata_constraints
from backend.prompt_validation import _local_temporal_assessment
from backend.validation_fixes import effective_temporal_range


@pytest.mark.parametrize(
    "prompt",
    [
        "classic rock from the 1960s to the 1990s",
        "rock dagli anni '60 agli anni '90",
        "rock des années 1960 aux années 1990",
        "rock de los años 1960 a los años 1990",
    ],
)
def test_decade_to_decade_ranges_are_continuous_intervals(prompt: str) -> None:
    assert _local_temporal_assessment(prompt) is None
    assert effective_temporal_range(prompt) == (1960, 1999)


def test_between_decades_with_and_is_a_range_not_an_intersection() -> None:
    prompt = "classic rock between the 1960s and the 1990s"

    assert _local_temporal_assessment(prompt) is None
    assert effective_temporal_range(prompt) == (1960, 1999)


def test_union_of_decades_remains_valid_without_additional_limits() -> None:
    assert (
        _local_temporal_assessment(
            "rock degli anni '80 e degli anni '90"
        )
        is None
    )


def test_additional_lower_bound_rejects_every_period_in_union() -> None:
    assessment = _local_temporal_assessment(
        "rock degli anni '80 e degli anni '90 pubblicato dopo il 2005"
    )

    assert assessment is not None
    assert assessment.status == "impossible"
    assert "2006" in assessment.reasons[0]
    assert "1999" in assessment.reasons[0]


def test_additional_bound_can_leave_one_period_in_union_valid() -> None:
    assert (
        _local_temporal_assessment(
            "rock degli anni '80 e degli anni '90 pubblicato dopo il 1995"
        )
        is None
    )


def test_nested_range_intersects_decade_instead_of_becoming_union() -> None:
    assert (
        _local_temporal_assessment(
            "rock degli anni '90 tra il 1995 e il 1998"
        )
        is None
    )

    assessment = _local_temporal_assessment(
        "rock degli anni '90 tra il 2001 e il 2005"
    )
    assert assessment is not None
    assert assessment.status == "impossible"


def test_contiguous_union_and_lower_bound_produce_exact_metadata_range() -> None:
    constraints = extract_metadata_constraints(
        "Crea una playlist rock di brani degli anni ’80 oppure degli anni ’90, "
        "ma solo pubblicati dopo il 1985."
    )

    assert constraints.release_year_from == 1986
    assert constraints.release_year_to == 1999


def test_separated_union_is_not_widened_into_a_single_range() -> None:
    constraints = extract_metadata_constraints(
        "brani tra il 1980 e il 1985 oppure tra il 2000 e il 2005"
    )

    assert not (
        constraints.release_year_from == 1980
        and constraints.release_year_to == 2005
    )
