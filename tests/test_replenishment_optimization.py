from backend import _optimized_replenishment_request


def _prompt(missing: int, request: str) -> str:
    return (
        f"The original playlist request is:\n{request}\n\n"
        f"The playlist still needs {missing} resolvable songs. "
        "Suggest exactly 8 NEW replacement candidates."
    )


def test_small_shortfall_uses_at_least_twelve_candidates():
    prompt, count = _optimized_replenishment_request(
        _prompt(
            2,
            "musica rock anni '90, più della metà delle canzoni deve essere dei Rolling Stones",
        ),
        8,
    )

    assert count == 12
    assert "Suggest exactly 12 NEW" in prompt
    assert "strict majority of tracks by Rolling Stones" in prompt


def test_larger_shortfall_scales_candidate_pool_without_exceeding_cap():
    prompt, count = _optimized_replenishment_request(
        _prompt(9, "musica rock anni '90"),
        18,
    )

    assert count == 30
    assert "Suggest exactly 30 NEW" in prompt
