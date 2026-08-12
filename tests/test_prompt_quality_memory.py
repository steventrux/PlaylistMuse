from __future__ import annotations

from backend.artist_quota_detection import (
    extract_artist_exact_quotas,
    extract_artist_minimum_quotas,
)
from backend.llm import SYSTEM_PROMPT
from backend.prompt_quality_memory import (
    approved_prompt_quality_cases,
    load_prompt_quality_memory,
)
from backend.recording_variants import (
    RecordingVariantPolicy,
    recording_filter_conflicts,
)
from backend.refinement_intent import studio_artist_addition_targets


def _as_dicts(items: list[object]) -> list[dict[str, object]]:
    return [
        {name: getattr(item, name) for name in item.__dataclass_fields__}
        for item in items
    ]


def test_prompt_quality_memory_is_versioned_unique_and_curated() -> None:
    memory = load_prompt_quality_memory()

    assert memory.schema_version == 1
    assert memory.cases
    assert len({case.id for case in memory.cases}) == len(memory.cases)
    assert all(case.failure and case.desired_behavior for case in memory.cases)
    assert all(case.expectations for case in memory.cases if case.status == "approved")


def test_only_approved_cases_are_available_for_future_runtime_guidance() -> None:
    approved = approved_prompt_quality_cases()

    assert approved
    assert all(case.status == "approved" for case in approved)


def test_approved_artist_minimum_regressions_remain_supported() -> None:
    cases = [
        case
        for case in approved_prompt_quality_cases()
        if "artist_minimum_quotas" in case.expectations
    ]
    assert cases

    for case in cases:
        expected = case.expectations["artist_minimum_quotas"]
        actual = _as_dicts(extract_artist_minimum_quotas(case.prompt))
        assert actual == expected, case.id


def test_approved_artist_exact_count_regressions_remain_supported() -> None:
    cases = [
        case
        for case in approved_prompt_quality_cases()
        if "artist_exact_quotas" in case.expectations
    ]
    assert cases

    for case in cases:
        expected = case.expectations["artist_exact_quotas"]
        actual = _as_dicts(extract_artist_exact_quotas(case.prompt))
        assert actual == expected, case.id


def test_approved_incremental_addition_regressions_remain_supported() -> None:
    cases = [
        case
        for case in approved_prompt_quality_cases(flow="studio")
        if "artist_addition_targets" in case.expectations
    ]
    assert cases

    for case in cases:
        expected = case.expectations["artist_addition_targets"]
        actual = _as_dicts(studio_artist_addition_targets(case.prompt))
        assert actual == expected, case.id


def test_recording_filter_conflict_cases_remain_blocking() -> None:
    cases = [
        case
        for case in approved_prompt_quality_cases(flow="generation")
        if "conflicting_option" in case.expectations
    ]
    assert cases

    for case in cases:
        required = frozenset(case.expectations.get("recording_required", []))
        options = dict(case.context.get("options") or {})
        conflicts = recording_filter_conflicts(
            options,
            RecordingVariantPolicy(required=required),
        )
        assert any(
            conflict.option == case.expectations["conflicting_option"]
            for conflict in conflicts
        ), case.id


def test_explicit_soft_curation_intent_is_playlist_wide_and_generalized() -> None:
    guidance = SYSTEM_PROMPT.casefold()

    assert "core musical brief" in guidance
    assert "mood, energy, activity or listening context" in guidance
    assert "playlist-wide selection objective" in guidance
    assert "generic popularity, variety, novelty or discovery" in guidance
    assert "party" not in guidance
    assert "festive" not in guidance


def test_mood_context_feedback_case_preserves_reported_options() -> None:
    cases = {
        case.id: case
        for case in approved_prompt_quality_cases(flow="generation")
    }
    case = cases["generation-preserves-explicit-mood-context-it"]

    assert case.origin == "user_feedback"
    assert case.context["options"] == {
        "exclude_live": True,
        "exclude_covers": False,
        "exclude_remixes": False,
    }
    assert case.expectations["release_year_from"] == 2000
    assert case.expectations["creative_intent"]["scope"] == "playlist_wide"
    assert case.expectations["selection_priority"] == (
        "explicit_soft_intent_before_generic_preferences"
    )
