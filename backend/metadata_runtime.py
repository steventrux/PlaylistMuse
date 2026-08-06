"""Shared metadata validation capacity controls."""

from __future__ import annotations

import os


class MetadataServiceUnavailableError(RuntimeError):
    """Raised when strict metadata verification cannot reach MusicBrainz."""


def metadata_lookup_limit(candidate_count: int) -> int:
    """Validate every candidate unless an administrator sets a limit."""
    raw = os.getenv("METADATA_VALIDATION_MAX_LOOKUPS")
    if raw is None:
        return candidate_count
    try:
        return max(0, int(raw))
    except ValueError:
        return candidate_count
