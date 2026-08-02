from backend.main import (
    SeedGenerateRequest,
    SeedTrack,
    _constraint_priority_prompt,
    _discovery_prompt,
    _replenishment_prompt,
    _seed_mode_instruction,
)


def test_constraint_priority_prompt_keeps_original_request_and_hard_filters():
    prompt = "Italian summer hits released in 2026 only"

    guarded = _constraint_priority_prompt(prompt)

    assert prompt in guarded
    assert "mandatory" in guarded
    assert "never relax" in guarded
    assert "Musical progression only" in guarded


def test_discovery_prompt_subordinates_lastfm_and_flow_to_user_constraints():
    guided = _discovery_prompt(
        "Italian summer hits released in 2026 only",
        {
            "tracks": [
                {
                    "artist": "Example Artist",
                    "title": "Example Song",
                }
            ]
        },
        [
            {
                "artist": "Suggested Artist",
                "title": "Suggested Song",
                "lastfm_strategy": "similar_track",
            }
        ],
        20,
    )

    assert "hard filters" in guided
    assert "Never silently broaden" in guided
    assert "Musical flow may only order already compliant tracks" in guided
    assert "Use Last.fm evidence only when it satisfies the original request" in guided


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
    assert "Most tracks should be close matches" in balanced
    assert "allow a wider sequence" in exploratory
    assert len({strict, balanced, exploratory}) == 3


def test_seed_request_defaults_to_balanced_and_accepts_all_modes():
    seed = SeedTrack(video_id="abcdefghijk", title="Seed Song", artists="Seed Artist")

    default_request = SeedGenerateRequest(seed=seed)
    strict_request = SeedGenerateRequest(seed=seed, seed_mode="strict")
    exploratory_request = SeedGenerateRequest(seed=seed, seed_mode="exploratory")

    assert default_request.seed_mode == "balanced"
    assert strict_request.seed_mode == "strict"
    assert exploratory_request.seed_mode == "exploratory"
