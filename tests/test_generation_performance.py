from backend import _optimized_replenishment_request, _stage_name
from backend.generation_runtime import (
    _creative_repair_rounds,
    _hard_constraint_guidance,
)
from backend.metadata_validation import MetadataConstraints


def test_replenishment_request_uses_wider_minimum_pool():
    prompt = (
        "The original playlist request is:\nRoad trip rock\n\n"
        "The playlist still needs 1 resolvable songs. Suggest exactly 8 NEW "
        "replacement candidates."
    )

    optimized_prompt, optimized_count = _optimized_replenishment_request(prompt, 8)

    assert optimized_count == 12
    assert "Suggest exactly 12 NEW" in optimized_prompt


def test_replenishment_request_scales_and_caps_pool():
    prompt = (
        "The original playlist request is:\nRoad trip rock\n\n"
        "The playlist still needs 12 resolvable songs. Suggest exactly 24 NEW "
        "replacement candidates."
    )

    optimized_prompt, optimized_count = _optimized_replenishment_request(prompt, 24)

    assert optimized_count == 30
    assert "Suggest exactly 30 NEW" in optimized_prompt


def test_non_replenishment_requests_remain_unchanged():
    prompt = "Create the final playlist for this request:\nRoad trip rock"

    optimized_prompt, optimized_count = _optimized_replenishment_request(prompt, 25)

    assert optimized_prompt == prompt
    assert optimized_count == 25


def test_generation_stage_classification():
    assert _stage_name("Create the final playlist for this request:\nRock") == "llm_guided"
    assert _stage_name("The original playlist request is:\nRock") == "llm_replenishment"
    assert (
        _stage_name("Suggest exactly 6 strong replacement candidates for one song")
        == "llm_replacement"
    )
    assert _stage_name("Follow the user's request literally") == "llm_initial"


def test_creative_regeneration_is_disabled_for_replenishment() -> None:
    assert _creative_repair_rounds("llm_replenishment") == 0
    assert _creative_repair_rounds("llm_initial") == 1
    assert _creative_repair_rounds("llm_guided") == 1
    assert _creative_repair_rounds("llm_replacement") == 1


def test_hard_constraint_guidance_exposes_only_enforced_metadata_rules() -> None:
    guidance = _hard_constraint_guidance(
        MetadataConstraints(
            release_year_from=2000,
            release_year_to=2026,
            excluded_artists=["Artist X"],
        )
    )

    assert "ENFORCED HARD CONSTRAINTS" in guidance
    assert "between 2000 and 2026, inclusive" in guidance
    assert "excluded artists: Artist X" in guidance
    assert "original-release chronology" in guidance


def test_hard_constraint_guidance_is_empty_for_unconstrained_request() -> None:
    assert _hard_constraint_guidance(MetadataConstraints()) == ""
