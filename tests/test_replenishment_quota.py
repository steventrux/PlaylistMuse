from backend import (
    _numeric_quota_replenishment_guidance,
    _optimized_replenishment_request,
    _quota_replenishment_guidance,
)


def _prompt(request: str, missing: int = 5) -> str:
    return (
        f"The original playlist request is:\n{request}\n\n"
        f"The playlist still needs {missing} resolvable songs. "
        "Suggest exactly 30 NEW replacement candidates."
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
    assert _numeric_quota_replenishment_guidance(prompt, 30) == ""


def test_optimized_replenishment_keeps_quota_guidance_and_widens_pool():
    prompt = _prompt(
        "musica rock anni '90, più della metà delle canzoni deve essere dei Rolling Stones",
        missing=3,
    )
    optimized_prompt, optimized_count = _optimized_replenishment_request(prompt, 30)
    assert optimized_count == 30
    assert "Suggest exactly 30 NEW" in optimized_prompt
    assert "QUOTA REPLENISHMENT" in optimized_prompt


def test_numeric_artist_quotas_get_separate_reserves():
    prompt = _prompt(
        "musica rock anni '90, almeno 4 canzoni devono essere dei Rolling Stones "
        "e 3 canzoni devono essere degli AC/DC",
        missing=1,
    )
    optimized_prompt, optimized_count = _optimized_replenishment_request(prompt, 12)
    assert optimized_count == 12
    assert "NUMERIC QUOTA REPLENISHMENT" in optimized_prompt
    assert "6 distinct candidates by Rolling Stones" in optimized_prompt
    assert "6 distinct candidates by AC/DC" in optimized_prompt
