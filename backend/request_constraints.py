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
_OPEN_ENDED_YEAR_PATTERNS = (
    re.compile(
        r"\b(?:dal|dall['’]?|a\s+partire\s+dal)\s+(?P<year>19\d{2}|20\d{2})\s+"
        r"(?:ad|a|fino\s+ad?|fino\s+a)\s+oggi\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bfrom\s+(?P<year>19\d{2}|20\d{2})\s+"
        r"(?:to|until|through)\s+(?:today|now|the\s+present)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:de|depuis)\s+(?P<year>19\d{2}|20\d{2})\s+"
        r"(?:à|a|jusqu['’]?(?:à|a))\s+(?:aujourd['’]?hui|maintenant|le\s+présent)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bdesde\s+(?P<year>19\d{2}|20\d{2})\s+"
        r"(?:hasta\s+)?(?:hoy|la\s+actualidad|ahora)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bvon\s+(?P<year>19\d{2}|20\d{2})\s+bis\s+"
        r"(?:heute|jetzt|zur\s+gegenwart)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bdesde\s+(?P<year>19\d{2}|20\d{2})\s+"
        r"(?:até|ate)\s+(?:hoje|agora|o\s+presente)\b",
        re.IGNORECASE,
    ),
)


def open_ended_year_range(
    prompt: str,
    *,
    current_year: int | None = None,
) -> tuple[int, int] | None:
    """Return an explicit decade/year-to-present range when wording proves it locally."""
    text = " ".join(str(prompt).split())
    end = current_year or datetime.now(UTC).year

    for pattern in _OPEN_ENDED_DECADE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        decade = int(match.group("decade"))
        start = 1900 + decade if decade >= 30 else 2000 + decade
        if start <= end:
            return start, end

    for pattern in _OPEN_ENDED_YEAR_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        start = int(match.group("year"))
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
