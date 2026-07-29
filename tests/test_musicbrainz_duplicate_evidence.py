"""Regression tests for duplicate MusicBrainz recording evidence."""

from backend.metadata.musicbrainz_policy import (
    _equivalent_recordings,
    _propagate_relationship_evidence,
)

EXCLUDE_COVERS = {
    "exclude_live": False,
    "exclude_covers": True,
    "exclude_remixes": False,
}


def _candidate(
    recording_mbid: str,
    *,
    length_ms: int,
    year: int = 2002,
    release_title: str = "American IV: The Man Comes Around",
    categories: list[str] | None = None,
) -> dict:
    return {
        "recording_mbid": recording_mbid,
        "recording_title": "Hurt",
        "length_ms": length_ms,
        "effective_release_year": year,
        "release_title": release_title,
        "release_status": "Official",
        "release_group_secondary_types": [],
        "lexical_score": 100.0,
        "duration_score": 90.0,
        "duration_delta_ms": 1_000,
        "release_quality_score": 100.0,
        "relationship_version_categories": categories or [],
    }


def test_propagates_cover_evidence_within_same_release_despite_duration_variance() -> None:
    documented = _candidate(
        "documented-cover",
        length_ms=217_000,
        categories=["cover"],
    )
    duplicate = _candidate("duplicate-without-relations", length_ms=233_000)

    assert _equivalent_recordings(documented, duplicate) is True

    propagated = _propagate_relationship_evidence(
        [documented, duplicate],
        EXCLUDE_COVERS,
    )

    assert propagated[1]["version_categories"] == ["cover"]
    assert propagated[1]["policy_excluded_categories"] == ["cover"]
    assert propagated[1]["matched"] is False
    assert propagated[1]["relationship_evidence_recording_mbids"] == [
        "documented-cover"
    ]


def test_does_not_propagate_cover_evidence_across_different_release_years() -> None:
    documented = _candidate(
        "documented-cover",
        length_ms=217_000,
        categories=["cover"],
    )
    distinct = _candidate(
        "distinct-performance",
        length_ms=218_000,
        year=2003,
        release_title="Different official release",
    )

    assert _equivalent_recordings(documented, distinct) is False

    propagated = _propagate_relationship_evidence(
        [documented, distinct],
        EXCLUDE_COVERS,
    )

    assert propagated[1]["version_categories"] == []
    assert propagated[1]["policy_excluded_categories"] == []
    assert propagated[1]["relationship_evidence_recording_mbids"] == []
