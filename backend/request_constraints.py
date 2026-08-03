"""Request-level constraint helpers that do not retain cross-request state."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from backend.artist_quota_detection import ArtistMinimumQuota

_OPEN_ENDED_DECADE_PATTERNS = (
    re.compile(
        r"\b(?:dagli|dai|a\s+partire\s+dagli)\s+anni\s+['’]?(?P<decade>\d{2})\s+"
        r"(?:ad|a)\s+oggi\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bfrom\s+the\s+['’]?(?P<decade>\d{2})s\s+(?:to|until)\s+today\b",
        re.IGNORECASE,
    ),
)


def open_ended_year_range(
    prompt: str,
    *,
    current_year: int | None = None,
) -> tuple[int, int] | None:
    """Return an explicit decade-to-present range when the wording proves it locally."""
    text = " ".join(str(prompt).split())
    for pattern in _OPEN_ENDED_DECADE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        decade = int(match.group("decade"))
        start = 1900 + decade if decade >= 30 else 2000 + decade
        end = current_year or datetime.now(UTC).year
        if start <= end:
            return start, end
    return None


def buffered_artist_quotas(
    quotas: list[ArtistMinimumQuota],
    requested_count: int,
    *,
    maximum_extra_per_artist: int = 2,
) -> list[ArtistMinimumQuota]:
    """Add a bounded resolution margin without exceeding the playlist capacity."""
    if not quotas or requested_count <= 0:
        return list(quotas)

    mandatory = sum(max(0, quota.minimum) for quota in quotas)
    spare = max(0, requested_count - mandatory)
    buffered: list[ArtistMinimumQuota] = []
    for quota in quotas:
        extra = min(maximum_extra_per_artist, spare)
        buffered.append(ArtistMinimumQuota(quota.artist, quota.minimum + extra))
        spare -= extra
    return buffered
