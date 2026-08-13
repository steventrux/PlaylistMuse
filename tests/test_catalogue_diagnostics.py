from __future__ import annotations

import logging
from types import SimpleNamespace

import backend.main as main_module
import backend.metadata_validation as metadata_validation


def test_metadata_reason_labels_group_validation_failures() -> None:
    temporal_unknown = {
        "unresolved_reason": "metadata_validation",
        "metadata_validation": {
            "status": "unknown",
            "violations": [],
            "warnings": [],
            "original_release_year": None,
            "artist_country": None,
        },
    }
    invalid_year = {
        "unresolved_reason": "metadata_validation",
        "metadata_validation": {
            "status": "invalid",
            "violations": ["release year 1998 is before 2000"],
            "warnings": [],
            "original_release_year": 1998,
            "artist_country": None,
        },
    }
    no_match = {
        "unresolved_reason": "metadata_validation",
        "metadata_validation": {
            "status": "unknown",
            "violations": [],
            "warnings": ["No MusicBrainz match"],
            "original_release_year": None,
            "artist_country": None,
        },
    }

    assert main_module._metadata_reason_labels(
        temporal_unknown,
        temporal_required=True,
        artist_country_required=False,
    ) == {"missing_release_year"}
    assert main_module._metadata_reason_labels(
        invalid_year,
        temporal_required=True,
        artist_country_required=False,
    ) == {"release_year"}
    assert main_module._metadata_reason_labels(
        no_match,
        temporal_required=True,
        artist_country_required=False,
    ) == {"no_musicbrainz_match"}


def test_catalogue_diagnostics_separate_resolution_layers(monkeypatch, caplog) -> None:
    monkeypatch.setattr(
        metadata_validation,
        "active_constraints",
        lambda: SimpleNamespace(
            release_year=None,
            release_year_from=2000,
            release_year_to=2026,
            artist_country=None,
        ),
    )
    unresolved = [
        {"artist": "A", "title": "YT miss"},
        {
            "artist": "B",
            "title": "Unknown year",
            "unresolved_reason": "metadata_validation",
            "metadata_validation": {
                "status": "unknown",
                "violations": [],
                "warnings": [],
                "original_release_year": None,
                "artist_country": None,
            },
        },
        {
            "artist": "C",
            "title": "Wrong year",
            "unresolved_reason": "metadata_validation",
            "metadata_validation": {
                "status": "invalid",
                "violations": ["release year 1997 is before 2000"],
                "warnings": [],
                "original_release_year": 1997,
                "artist_country": None,
            },
        },
        {
            "artist": "D",
            "title": "Live version",
            "unresolved_reason": "recording_variant",
        },
    ]

    with caplog.at_level(logging.INFO, logger="playlistmuse.performance"):
        main_module._log_catalogue_diagnostics(
            "initial",
            [{"artist": str(index), "title": "Track"} for index in range(5)],
            [{"artists": "E", "title": "Selected"}],
            unresolved,
            playlist_before=0,
        )

    message = next(
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("catalogue_diagnostics ")
    )
    assert "stage=initial" in message
    assert "candidates=5" in message
    assert "selected=1" in message
    assert "'youtube_resolution': 1" in message
    assert "'metadata_validation': 2" in message
    assert "'recording_variant': 1" in message
    assert "'missing_release_year': 1" in message
    assert "'release_year': 1" in message
