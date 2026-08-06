import backend


def test_catalogue_quota_state_is_not_global():
    assert not hasattr(backend, "_ACTIVE_ARTIST_QUOTAS")
    assert not hasattr(backend, "_RESOLVED_QUOTA_TRACKS")
    assert not hasattr(backend, "_REQUESTED_TRACK_COUNT")


def test_generic_replenishment_has_no_artist_quota_state_guidance():
    prompt = (
        "The original playlist request is:\n"
        "un viaggio nella storia del rock, dagli anni 60 ad oggi\n\n"
        "The playlist still needs 4 resolvable songs. Suggest exactly 8 NEW "
        "replacement candidates."
    )

    optimized, count = backend._optimized_replenishment_request(prompt, 8)

    assert count == 16
    assert "RESOLVED QUOTA DEFICITS" not in optimized
    assert "Rolling Stones" not in optimized
    assert "AC/DC" not in optimized
