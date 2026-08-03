from backend import _optimized_replenishment_request, _stage_name


def test_replenishment_request_reduces_oversized_minimum_pool():
    prompt = (
        "The original playlist request is:\nRoad trip rock\n\n"
        "The playlist still needs 1 resolvable songs. Suggest exactly 8 NEW "
        "replacement candidates."
    )

    optimized_prompt, optimized_count = _optimized_replenishment_request(prompt, 8)

    assert optimized_count == 4
    assert "Suggest exactly 4 NEW" in optimized_prompt


def test_replenishment_request_scales_and_caps_pool():
    prompt = (
        "The original playlist request is:\nRoad trip rock\n\n"
        "The playlist still needs 12 resolvable songs. Suggest exactly 24 NEW "
        "replacement candidates."
    )

    optimized_prompt, optimized_count = _optimized_replenishment_request(prompt, 24)

    assert optimized_count == 20
    assert "Suggest exactly 20 NEW" in optimized_prompt


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
