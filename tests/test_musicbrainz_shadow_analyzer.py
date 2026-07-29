"""Tests for the offline MusicBrainz shadow report."""

from __future__ import annotations

import json

from scripts import analyze_musicbrainz_shadow as analyzer


def _result(
    *,
    title: str,
    mbid: str,
    decision: str = "matched",
    attempts: int = 1,
    categories: list[str] | None = None,
    reasons: list[str] | None = None,
) -> dict:
    return {
        "input": {
            "title": title,
            "artists": "Artist",
            "duration": "4:00",
        },
        "attempts": attempts,
        "musicbrainz": {
            "recording_mbid": mbid,
            "decision": decision,
            "decision_reasons": reasons or [],
            "version_categories": categories or [],
            "confidence": 95.0,
            "duration_delta_ms": 1000,
            "relationship_lookup_complete": True,
            "relationship_version_categories": categories or [],
        },
    }


def test_load_and_analyze_shadow_records_handles_malformed_lines(tmp_path) -> None:
    path = tmp_path / "shadow.ndjson"
    first = {
        "schema_version": 3,
        "exclusions": {
            "exclude_live": True,
            "exclude_covers": True,
            "exclude_remixes": True,
        },
        "results": [
            _result(title="Song", mbid="mbid-1", attempts=2),
            {
                "input": {"title": "Other", "artists": "Artist"},
                "attempts": 3,
                "musicbrainz": None,
                "error": "ReadTimeout",
            },
        ],
    }
    second = {
        "schema_version": 3,
        "exclusions": {
            "exclude_live": False,
            "exclude_covers": True,
            "exclude_remixes": False,
        },
        "results": [
            _result(
                title="Live Song",
                mbid="mbid-live",
                decision="ambiguous",
                categories=["live"],
                reasons=["excluded_live"],
            )
        ],
    }
    path.write_text(
        json.dumps(first) + "\n" + "not-json\n" + json.dumps(second) + "\n",
        encoding="utf-8",
    )

    records, malformed = analyzer.load_records(path)
    report = analyzer.analyze_records(records, malformed_lines=malformed)

    assert len(records) == 2
    assert malformed == [2]
    assert report["record_count"] == 2
    assert report["sampled_result_count"] == 3
    assert report["decisions"] == {"ambiguous": 1, "matched": 1}
    assert report["errors"] == {"ReadTimeout": 1}
    assert report["attempts"] == {"1": 1, "2": 1, "3": 1}
    assert report["retry_recovered_count"] == 1
    assert report["version_categories"] == {"live": 1}
    assert report["decision_reasons"] == {"excluded_live": 1}
    assert report["malformed_lines"] == [2]


def test_analyzer_detects_repeated_identity_with_unstable_mbid() -> None:
    records = [
        {
            "exclusions": {},
            "results": [_result(title="Same Song", mbid="mbid-a")],
        },
        {
            "exclusions": {},
            "results": [_result(title="Same Song", mbid="mbid-b")],
        },
    ]

    report = analyzer.analyze_records(records)

    identity = "artist::same song"
    assert report["repeated_identities"] == {identity: 2}
    assert report["unstable_recording_mbids"] == {
        identity: ["mbid-a", "mbid-b"]
    }


def test_render_text_contains_operational_summary() -> None:
    report = analyzer.analyze_records(
        [
            {
                "exclusions": {},
                "results": [_result(title="Song", mbid="mbid-1", attempts=2)],
            }
        ]
    )

    text = analyzer.render_text(report)

    assert "MUSICBRAINZ SHADOW REPORT" in text
    assert "Decisioni: matched: 1" in text
    assert "Retry recuperati: 1" in text
    assert "Identità con MBID instabile: 0" in text
