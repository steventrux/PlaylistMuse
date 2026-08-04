"""Install cross-cutting safeguards before application routes import dependencies."""

from __future__ import annotations

from backend.metadata_runtime import (
    metadata_filter,
    metadata_rate_limited_get,
    search_artist,
    verify_album_artist_pair,
)
from backend.policy_consistency import apply_playlist_policy
from backend.policy_enforcement import install_generation_policy_wrapper
from backend.selection_guard import guarded_select_resolved_tracks
from backend.validation_fixes import (
    quota_extractor,
    safe_error_message,
    temporal_assessment,
)


def install_pre_generation_fixes() -> None:
    """Patch dependencies before generation wrappers capture their callables."""
    from backend import (
        artist_quota_detection,
        constraint_relationships,
        entity_resolution,
        generation_runtime,
        llm,
        metadata_validation,
        playlist_policy,
        policy_enforcement,
        prompt_validation,
        youtube,
    )

    if getattr(install_pre_generation_fixes, "_installed", False):
        return

    playlist_policy.apply_playlist_policy = apply_playlist_policy
    policy_enforcement.apply_playlist_policy = apply_playlist_policy
    prompt_validation._local_temporal_assessment = temporal_assessment
    artist_quota_detection.extract_artist_minimum_quotas = quota_extractor(
        artist_quota_detection.extract_artist_minimum_quotas
    )
    youtube._metadata_filter = metadata_filter
    llm.safe_error_message = safe_error_message
    metadata_validation._rate_limited_get = metadata_rate_limited_get
    entity_resolution._search_artist = search_artist
    constraint_relationships._verify_album_artist_pair = verify_album_artist_pair
    generation_runtime._select_resolved_tracks = guarded_select_resolved_tracks
    install_pre_generation_fixes._installed = True  # type: ignore[attr-defined]


def install_post_generation_fixes() -> None:
    """Install policy persistence after the base generation wrappers are ready."""
    install_generation_policy_wrapper()
