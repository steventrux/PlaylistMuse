"""Tests for conservative MusicBrainz shadow decisions."""

from backend.metadata.musicbrainz_decision import classify_musicbrainz_match


def test_accepts_clean_high_confidence_match() -> None:
    decision = classify_musicbrainz_match(
        {
            "matched": True,
            "recording_mbid": "recording",
            "lexical_score": 100,
            "version_penalty": 0,
            "duration_delta_ms": 2000,
        }
    )

    assert decision == {
        "decision": "matched",
        "safe_match": True,
        "ambiguous": False,
        "decision_reasons": [],
    }


def test_downgrades_live_result_to_ambiguous() -> None:
    decision = classify_musicbrainz_match(
        {
            "matched": False,
            "recording_mbid": "live-recording",
            "lexical_score": 100,
            "version_penalty": 35,
            "duration_delta_ms": 1200,
        }
    )

    assert decision["decision"] == "ambiguous"
    assert decision["safe_match"] is False
    assert decision["decision_reasons"] == ["alternate_version"]


def test_downgrades_large_duration_difference_to_ambiguous() -> None:
    decision = classify_musicbrainz_match(
        {
            "matched": False,
            "recording_mbid": "short-version",
            "lexical_score": 100,
            "version_penalty": 0,
            "duration_delta_ms": 25894,
        }
    )

    assert decision["decision"] == "ambiguous"
    assert decision["decision_reasons"] == ["duration_mismatch"]


def test_rejects_non_matching_title_or_artist() -> None:
    decision = classify_musicbrainz_match(
        {
            "matched": False,
            "recording_mbid": "wrong-recording",
            "lexical_score": 61,
            "version_penalty": 0,
            "duration_delta_ms": 1000,
        }
    )

    assert decision["decision"] == "rejected"
    assert decision["ambiguous"] is False
    assert decision["decision_reasons"] == ["title_or_artist_mismatch"]
