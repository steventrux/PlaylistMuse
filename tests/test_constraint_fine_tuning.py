from __future__ import annotations

from backend.config import AppConfig
from backend.constraint_interpreter import (
    INTERPRETER_PROMPT_VERSION,
    INTERPRETER_SCHEMA_VERSION,
    _cache_key,
    _unwrap_cached_payload,
)
from backend.metadata_validation import (
    MetadataConstraints,
    TrackMetadata,
    constraints_from_payload,
    validate_metadata,
)


def test_cache_key_changes_with_interpreter_version_and_model():
    first = AppConfig(provider="custom", model="model-a", base_url="http://localhost")
    second = AppConfig(provider="custom", model="model-b", base_url="http://localhost")

    assert _cache_key(first, "Rock anni 90") != _cache_key(second, "Rock anni 90")
    assert INTERPRETER_SCHEMA_VERSION >= 2
    assert INTERPRETER_PROMPT_VERSION


def test_cache_payload_requires_current_versions():
    interpretation = {"allowed_artists": ["Metallica"]}
    current = {
        "schema_version": INTERPRETER_SCHEMA_VERSION,
        "prompt_version": INTERPRETER_PROMPT_VERSION,
        "interpretation": interpretation,
    }
    stale = {**current, "schema_version": INTERPRETER_SCHEMA_VERSION - 1}

    assert _unwrap_cached_payload(current) == interpretation
    assert _unwrap_cached_payload(stale) is None


def test_only_high_confidence_fields_become_hard_constraints():
    payload = {
        "allowed_artists": ["Metallica"],
        "release_year_from": 1990,
        "release_year_to": 1999,
        "field_confidence": {
            "allowed_artists": 0.97,
            "release_year_from": 0.72,
            "release_year_to": 0.72,
        },
    }

    constraints = constraints_from_payload(payload)

    assert constraints.allowed_artists == ["Metallica"]
    assert constraints.release_year_from is None
    assert constraints.release_year_to is None


def test_low_confidence_fields_preserve_local_fallback():
    fallback = MetadataConstraints(release_year_from=1990, release_year_to=1999)
    payload = {
        "release_year_from": 2000,
        "release_year_to": 2009,
        "field_confidence": {
            "release_year_from": 0.40,
            "release_year_to": 0.40,
        },
    }

    constraints = constraints_from_payload(payload, fallback=fallback)

    assert constraints.release_year_from == 1990
    assert constraints.release_year_to == 1999


def test_legacy_aliases_remain_compatible():
    constraints = MetadataConstraints(artist_name="Metallica", album_name="Load")

    assert constraints.allowed_artists == ["Metallica"]
    assert constraints.allowed_albums == ["Load"]
    assert constraints.artist_name == "Metallica"
    assert constraints.album_name == "Load"


def test_explicit_track_exception_overrides_general_year_and_artist_filters():
    metadata = TrackMetadata(
        artist="AC/DC",
        title="Highway to Hell",
        matched_artist="AC/DC",
        original_release_year=1979,
        release_titles=["Highway to Hell"],
        match_score=0.98,
        confidence="high",
    )
    constraints = MetadataConstraints(
        release_year_from=1990,
        release_year_to=1999,
        allowed_artists=["Metallica"],
        exception_tracks=[{"artist": "AC/DC", "title": "Highway to Hell"}],
    )

    result = validate_metadata(metadata, constraints)

    assert result.status == "valid"
    assert result.violations == []


def test_weak_metadata_cannot_use_exception_bypass():
    metadata = TrackMetadata(
        artist="AC/DC",
        title="Highway to Hell",
        matched_artist="AC/DC",
        original_release_year=1979,
        match_score=0.30,
        confidence="low",
    )
    constraints = MetadataConstraints(
        release_year_from=1990,
        exception_tracks=[{"artist": "AC/DC", "title": "Highway to Hell"}],
    )

    result = validate_metadata(metadata, constraints)

    assert result.status == "invalid"
    assert "release year 1979 is before 1990" in result.violations


def test_contradictions_are_recorded_without_activating_untrusted_fields():
    payload = {
        "release_year_from": 2020,
        "release_year_to": 1990,
        "contradictions": ["The requested date bounds conflict"],
        "field_confidence": {
            "release_year_from": 0.20,
            "release_year_to": 0.20,
        },
    }

    constraints = constraints_from_payload(payload)

    assert constraints.release_year_from is None
    assert constraints.release_year_to is None
    assert constraints.contradictions == ["The requested date bounds conflict"]
    assert constraints.active is False
