from backend.prompt_validation import _local_temporal_assessment


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
