from backend.main import (
    SeedGenerateRequest,
    SeedTrack,
    _constraint_priority_prompt,
    _replenishment_prompt,
    _seed_evidence_guidance,
    _seed_lastfm_evidence_params,
    _seed_mode_instruction,
)


def test_constraint_priority_prompt_keeps_original_request_and_hard_filters():
    prompt = "Italian summer hits released in 2026 only"

    guarded = _constraint_priority_prompt(prompt)

    assert prompt in guarded
    assert "mandatory" in guarded
    assert "never relax" in guarded
    assert "Use musical progression only to order tracks" in guarded


def test_seed_evidence_guidance_folds_lastfm_signals_without_a_second_pass():
    guidance = _seed_evidence_guidance(
        [
            {
                "artist": "Suggested Artist",
                "title": "Suggested Song",
                "lastfm_strategy": "similar_track",
            }
        ],
        seed_mode="strict",
    )

    assert "Suggested Artist" in guidance
    assert "Suggested Song" in guidance
    assert "primary mandatory criterion" in guidance  # strict seed-mode instruction
    assert "Use this evidence only when it satisfies the original request" in guidance
    assert "first-pass ideas" not in guidance.lower()


def test_replenishment_prompt_does_not_relax_constraints_to_fill_count():
    refill = _replenishment_prompt(
        "Italian summer hits released in 2026 only",
        "Estate 2026",
        "Current Italian summer releases.",
        3,
        8,
        [],
        [],
    )

    assert "remains mandatory during replenishment" in refill
    assert "Do not broaden dates, years, language, country" in refill
    assert "satisfy every original constraint" in refill


def test_seed_modes_have_distinct_similarity_rules():
    strict = _seed_mode_instruction("strict")
    balanced = _seed_mode_instruction("balanced")
    exploratory = _seed_mode_instruction("exploratory")

    assert "primary mandatory criterion" in strict
    assert "close matches supported by Last.fm" in balanced
    assert "real journey" in exploratory
    assert len({strict, balanced, exploratory}) == 3


def test_seed_lastfm_evidence_params_vary_by_mode():
    strict_limit, strict_broaden = _seed_lastfm_evidence_params("strict", 20)
    balanced_limit, balanced_broaden = _seed_lastfm_evidence_params("balanced", 20)
    exploratory_limit, exploratory_broaden = _seed_lastfm_evidence_params("exploratory", 20)

    assert strict_broaden is False
    assert balanced_broaden is False
    assert exploratory_broaden is True
    assert strict_limit < balanced_limit == exploratory_limit


def test_seed_request_defaults_to_balanced_and_accepts_all_modes():
    seed = SeedTrack(video_id="abcdefghijk", title="Seed Song", artists="Seed Artist")

    default_request = SeedGenerateRequest(seed=seed)
    strict_request = SeedGenerateRequest(seed=seed, seed_mode="strict")
    exploratory_request = SeedGenerateRequest(seed=seed, seed_mode="exploratory")

    assert default_request.seed_mode == "balanced"
    assert strict_request.seed_mode == "strict"
    assert exploratory_request.seed_mode == "exploratory"
