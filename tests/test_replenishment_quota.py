from backend import _optimized_replenishment_request, _quota_replenishment_guidance


def _prompt(request: str, missing: int = 5) -> str:
    return (
        f"The original playlist request is:\n{request}\n\n"
        "The playlist still needs "
        f"{missing} resolvable songs. Suggest exactly 30 NEW replacement candidates."
    )


def test_strict_majority_guidance_extracts_only_artist_name():
    prompt = _prompt(
        "musica rock anni '90, più della metà delle canzoni deve essere dei Rolling Stones"
    )

    guidance = _quota_replenishment_guidance(prompt)

    assert "tracks by Rolling Stones" in guidance
    assert "canzoni deve essere" not in guidance
    assert "three quarters" in guidance


def test_non_quota_replenishment_gets_no_artist_guidance():
    prompt = _prompt("musica rock anni '90")

    assert _quota_replenishment_guidance(prompt) == ""


def test_optimized_replenishment_keeps_quota_guidance_and_widens_pool():
    prompt = _prompt(
        "musica rock anni '90, più della metà delle canzoni deve essere dei Rolling Stones",
        missing=3,
    )

    optimized_prompt, optimized_count = _optimized_replenishment_request(prompt, 30)

    assert optimized_count == 30
    assert "Suggest exactly 30 NEW" in optimized_prompt
    assert "QUOTA REPLENISHMENT" in optimized_prompt
