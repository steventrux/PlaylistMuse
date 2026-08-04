"""PlaylistMuse backend package bootstrap."""

import backend.generation_runtime as _generation_runtime

from backend.generation_runtime import (
    _ACTIVE_RESOLUTION_QUOTAS,
    _REQUESTED_SESSION_COUNT,
    _RESOLVED_SESSION_TRACKS,
    _album_key,
    _constraint_source,
    _diversity_rank,
    _numeric_quota_replenishment_guidance,
    _optimized_replenishment_request,
    _quota_replenishment_guidance,
    _reset_resolution_session,
    _stage_name,
    install_generation_wrappers,
)
from backend.runtime_fixes import (
    install_post_generation_fixes,
    install_pre_generation_fixes,
)

install_pre_generation_fixes()
_select_resolved_tracks = _generation_runtime._select_resolved_tracks
install_generation_wrappers()
install_post_generation_fixes()

__all__ = [
    "_ACTIVE_RESOLUTION_QUOTAS",
    "_REQUESTED_SESSION_COUNT",
    "_RESOLVED_SESSION_TRACKS",
    "_album_key",
    "_constraint_source",
    "_diversity_rank",
    "_numeric_quota_replenishment_guidance",
    "_optimized_replenishment_request",
    "_quota_replenishment_guidance",
    "_reset_resolution_session",
    "_select_resolved_tracks",
    "_stage_name",
    "install_generation_wrappers",
]
