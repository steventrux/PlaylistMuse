"""Install the remaining shared-service adapters before generation starts."""

from __future__ import annotations

from backend.metadata_runtime import (
    metadata_filter,
    metadata_rate_limited_get,
    search_artist,
    verify_album_artist_pair,
)
from backend.validation_fixes import safe_error_message


def install_pre_generation_fixes() -> None:
    """Install only adapters not yet owned directly by their source modules."""
    from backend import (
        constraint_relationships,
        entity_resolution,
        llm,
        metadata_validation,
        youtube,
    )

    if getattr(install_pre_generation_fixes, "_installed", False):
        return

    youtube._metadata_filter = metadata_filter
    llm.safe_error_message = safe_error_message
    metadata_validation._rate_limited_get = metadata_rate_limited_get
    entity_resolution._search_artist = search_artist
    constraint_relationships._verify_album_artist_pair = verify_album_artist_pair
    install_pre_generation_fixes._installed = True  # type: ignore[attr-defined]
