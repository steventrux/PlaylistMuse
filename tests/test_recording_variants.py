from __future__ import annotations

import asyncio

import pytest

from backend import generation_runtime, youtube
from backend.playlist_studio import _validate_recording_scope
from backend.recording_variants import (
    RecordingVariantPolicy,
    activate_recording_policy,
    effective_resolver_options,
    policy_from_payload,
    recording_filter_conflicts,
    recording_variant_violations,
    reset_recording_policy,
)


def _track(title: str, album: str = "Studio Album") -> dict[str, str]:
    return {
        "video_id": title.casefold().replace(" ", "-"),
        "title": title,
        "artists": "Test Artist",
        "album": album,
    }


def test_low_confidence_recording_policy_is_not_enforced() -> None:
    policy = policy_from_payload(
        {
            "required_recording_types": ["live"],
            "recording_type_confidence": 0.4,
        }
    )

    assert policy.required == frozenset()


def test_required_live_conflicts_with_exclude_live_filter() -> None:
    policy = RecordingVariantPolicy(required=frozenset({"live"}), confidence=1.0)
    conflicts = recording_filter_conflicts(
        {
            "exclude_live": True,
            "exclude_covers": False,
            "exclude_remixes": False,
        },
        policy,
    )

    assert len(conflicts) == 1
    assert conflicts[0].option == "exclude_live"
    assert "Exclude live tracks" in conflicts[0].message


def test_refinement_can_override_inherited_recording_exclusion() -> None:
    policy = RecordingVariantPolicy(required=frozenset({"live"})).for_refinement()
    effective = effective_resolver_options(
        {
            "exclude_live": True,
            "exclude_covers": True,
            "exclude_remixes": True,
        },
        policy,
    )

    assert effective["exclude_live"] is False
    assert effective["exclude_covers"] is True
    assert effective["exclude_remixes"] is True


def test_required_live_rejects_studio_track_and_accepts_identified_live_track() -> None:
    policy = RecordingVariantPolicy(required=frozenset({"live"}))

    assert recording_variant_violations([_track("Studio Song")], policy)
    assert not recording_variant_violations([_track("Song (Live at Wembley)")], policy)


def test_playlist_studio_enforces_recording_version_on_editable_scope() -> None:
    policy = RecordingVariantPolicy(required=frozenset({"live"})).for_refinement()

    with pytest.raises(ValueError, match="recording-version constraint"):
        _validate_recording_scope(
            [_track("Song (Live)"), _track("Studio Song")],
            policy,
        )

    _validate_recording_scope(
        [_track("Song (Live)"), _track("Another Song", "Live in London")],
        policy,
    )


def test_catalogue_resolution_filters_non_live_results(monkeypatch) -> None:
    async def fake_resolve(candidates, exclusions):
        assert exclusions["exclude_live"] is False
        return (
            [_track("Song (Live)"), _track("Studio Song")],
            [],
        )

    monkeypatch.setattr(youtube, "resolve_candidates", fake_resolve)
    monkeypatch.setattr(
        generation_runtime,
        "_select_resolved_tracks",
        lambda resolved, **_: resolved,
    )

    token = activate_recording_policy(
        RecordingVariantPolicy(required=frozenset({"live"}), override_exclusions=True)
    )
    try:
        resolved, unresolved = asyncio.run(
            generation_runtime.resolve_candidates(
                [{"artist": "Test Artist", "title": "Song"}],
                {
                    "exclude_live": True,
                    "exclude_covers": True,
                    "exclude_remixes": True,
                },
            )
        )
    finally:
        reset_recording_policy(token)

    assert [track["title"] for track in resolved] == ["Song (Live)"]
    assert unresolved[0]["title"] == "Studio Song"
    assert unresolved[0]["unresolved_reason"] == "recording_variant_validation"


def test_initial_resolution_refuses_filter_conflict_before_catalogue_lookup(monkeypatch) -> None:
    called = False

    async def fake_resolve(candidates, exclusions):
        nonlocal called
        called = True
        return [], []

    monkeypatch.setattr(youtube, "resolve_candidates", fake_resolve)
    token = activate_recording_policy(
        RecordingVariantPolicy(required=frozenset({"live"}))
    )
    try:
        with pytest.raises(ValueError, match="Exclude live tracks"):
            asyncio.run(
                generation_runtime.resolve_candidates(
                    [{"artist": "Test Artist", "title": "Song"}],
                    {
                        "exclude_live": True,
                        "exclude_covers": False,
                        "exclude_remixes": False,
                    },
                )
            )
    finally:
        reset_recording_policy(token)

    assert called is False
