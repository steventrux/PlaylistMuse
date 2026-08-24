"""Request-level constraint helpers that do not retain cross-request state."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from backend.artist_quota_detection import ArtistMinimumQuota

# Genre/era adjectives meaning "today's music" (e.g. "modern jazz", "jazz moderno"),
# used to recognize wording like "the 1970s through modern jazz" as open-ended, the
# same as literal "to now/today/the present" phrasing. Covers the five languages this
# project's prompt parsing must support (EN/IT/FR/ES/DE), plus PT for parity with the
# literal year-to-present patterns below, which already include it. FR/ES/DE/PT are
# best-effort translations, not verified against native usage the way EN/IT are.
_GENRE_ERA_ADJECTIVES_IT = (
    r"moderno|moderna|moderni|moderne|"
    r"contemporaneo|contemporanea|contemporanei|contemporanee|"
    r"attuale|attuali"
)
_GENRE_ERA_ADJECTIVES_FR = r"moderne|contemporain|contemporaine|actuel|actuelle"
_GENRE_ERA_ADJECTIVES_ES = (
    r"moderno|moderna|modernos|modernas|"
    r"contempor[aá]neo|contempor[aá]nea|contempor[aá]neos|contempor[aá]neas|"
    r"actual|actuales"
)
_GENRE_ERA_ADJECTIVES_DE = (
    r"modernen?|modern|zeitgen[oö]ssischen?|zeitgen[oö]ssisch|aktuellen?|aktuell"
)
_GENRE_ERA_ADJECTIVES_PT = (
    r"moderno|moderna|modernos|modernas|"
    r"contempor[aâ]neo|contempor[aâ]nea|contempor[aâ]neos|contempor[aâ]neas|"
    r"atual|atuais"
)
_OPEN_ENDED_DECADE_PATTERNS = (
    re.compile(
        r"\b(?:dagli|dai|a\s+partire\s+dagli)\s+anni\s+['’]?(?P<decade>\d{2}|19\d0|20\d0)\s+"
        r"(?:ad|a|fino\s+ad?|fino\s+a)\s+(?:oggi|ora|adesso)\b",
        re.IGNORECASE,
    ),
    # A decade followed by a genre/era label meaning today's music (e.g. "fino al
    # jazz moderno") is temporally open-ended, just like "ad oggi" -- the genre word
    # sits between the article and the adjective in Italian ("al <genere> moderno").
    re.compile(
        r"\b(?:dagli|dai|a\s+partire\s+dagli)\s+anni\s+['’]?(?P<decade>\d{2}|19\d0|20\d0)\s+"
        rf"fino\s+(?:al|alla|ai|alle)\s+\w+\s+(?:{_GENRE_ERA_ADJECTIVES_IT})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bfrom\s+the\s+['’]?(?P<decade>\d{2}|19\d0|20\d0)s\s+"
        r"(?:to|until|through)\s+(?:today|now|the\s+present)\b",
        re.IGNORECASE,
    ),
    # A decade followed by a genre/era label meaning today's music (e.g. "through
    # modern jazz", "to current pop") is temporally open-ended, just like "to now".
    re.compile(
        r"\bfrom\s+the\s+['’]?(?P<decade>\d{2}|19\d0|20\d0)s\s+"
        r"(?:to|until|through)\s+(?:modern|contemporary|current)(?:\s+\w+)?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:des|depuis\s+les|à\s+partir\s+des)\s+ann[ée]es\s+['’]?(?P<decade>\d{2}|19\d0|20\d0)\s+"
        r"(?:à|jusqu['’]?(?:à|au|aux))\s+(?:aujourd['’]?hui|maintenant|le\s+présent)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:des|depuis\s+les|à\s+partir\s+des)\s+ann[ée]es\s+['’]?(?P<decade>\d{2}|19\d0|20\d0)\s+"
        rf"jusqu['’]?(?:au|à\s+la|aux)\s+\w+\s+(?:{_GENRE_ERA_ADJECTIVES_FR})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bdesde\s+los\s+a[ñn]os\s+['’]?(?P<decade>\d{2}|19\d0|20\d0)\s+"
        r"(?:hasta\s+)?(?:hoy|la\s+actualidad|ahora)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bdesde\s+los\s+a[ñn]os\s+['’]?(?P<decade>\d{2}|19\d0|20\d0)\s+"
        rf"hasta\s+(?:el|la|los|las)\s+\w+\s+(?:{_GENRE_ERA_ADJECTIVES_ES})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:aus|von)\s+den\s+['’]?(?P<decade>\d{2}|19\d0|20\d0)(?:er\s+Jahren?|ern)\s+bis\s+"
        r"(?:heute|jetzt|zur\s+gegenwart)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:aus|von)\s+den\s+['’]?(?P<decade>\d{2}|19\d0|20\d0)(?:er\s+Jahren?|ern)\s+bis\s+"
        rf"(?:zum|zur|zu\s+den)?\s*(?:{_GENRE_ERA_ADJECTIVES_DE})\s+\w+\b",
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
        r"\b(?:dal|dall['’]?|a\s+partire\s+dal)\s+(?P<year>19\d{2}|20\d{2})\s+"
        rf"fino\s+(?:al|alla|ai|alle)\s+\w+\s+(?:{_GENRE_ERA_ADJECTIVES_IT})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bfrom\s+(?P<year>19\d{2}|20\d{2})\s+"
        r"(?:to|until|through)\s+(?:today|now|the\s+present)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bfrom\s+(?P<year>19\d{2}|20\d{2})\s+"
        r"(?:to|until|through)\s+(?:modern|contemporary|current)(?:\s+\w+)?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:de|depuis)\s+(?P<year>19\d{2}|20\d{2})\s+"
        r"(?:à|a|jusqu['’]?(?:à|a))\s+(?:aujourd['’]?hui|maintenant|le\s+présent)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:de|depuis)\s+(?P<year>19\d{2}|20\d{2})\s+"
        rf"jusqu['’]?(?:au|à\s+la|aux)\s+\w+\s+(?:{_GENRE_ERA_ADJECTIVES_FR})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bdesde\s+(?P<year>19\d{2}|20\d{2})\s+"
        r"(?:hasta\s+)?(?:hoy|la\s+actualidad|ahora)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bdesde\s+(?P<year>19\d{2}|20\d{2})\s+"
        rf"hasta\s+(?:el|la|los|las)\s+\w+\s+(?:{_GENRE_ERA_ADJECTIVES_ES})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bvon\s+(?P<year>19\d{2}|20\d{2})\s+bis\s+"
        r"(?:heute|jetzt|zur\s+gegenwart)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bvon\s+(?P<year>19\d{2}|20\d{2})\s+bis\s+"
        rf"(?:zum|zur|zu\s+den)?\s*(?:{_GENRE_ERA_ADJECTIVES_DE})\s+\w+\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bdesde\s+(?P<year>19\d{2}|20\d{2})\s+"
        r"(?:até|ate)\s+(?:hoje|agora|o\s+presente)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bdesde\s+(?P<year>19\d{2}|20\d{2})\s+"
        rf"(?:até|ate)\s+(?:o|a|os|as)\s+\w+\s+(?:{_GENRE_ERA_ADJECTIVES_PT})\b",
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
        start = decade if decade >= 1000 else (1900 + decade if decade >= 30 else 2000 + decade)
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
