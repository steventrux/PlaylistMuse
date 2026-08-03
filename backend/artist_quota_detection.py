"""Deterministic extraction and checking of per-artist playlist quotas."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

_REQUEST_MARKERS = (
    "User request:\n",
    "The original playlist request is:\n",
    "Create the final playlist for this request:\n",
)

# Italian forms covered intentionally:
# - almeno 4 canzoni devono essere dei Rolling Stones
# - 3 canzoni devono essere degli AC/DC
# - minimo 2 brani di Metallica
_IT_MINIMUM_RE = re.compile(
    r"(?:\b(?:almeno|minimo|min\.)\s+)?"
    r"(?P<count>\d{1,3})\s+"
    r"(?:canzoni|brani|tracce|pezzi)\s*"
    r"(?:devono?\s+essere\s+|(?:devono?\s+)?provenire\s+da\s+)?"
    r"(?:di|dei|degli|delle|da|dagli|dalle)\s+"
    r"(?P<artist>[^,;.!\n]+)",
    re.IGNORECASE,
)

_EN_MINIMUM_RE = re.compile(
    r"(?:\b(?:at\s+least|minimum(?:\s+of)?)\s+)?"
    r"(?P<count>\d{1,3})\s+"
    r"(?:songs|tracks)\s+(?:must\s+be\s+)?(?:by|from)\s+"
    r"(?P<artist>[^,;.!\n]+)",
    re.IGNORECASE,
)

_TRAILING_CONNECTOR_RE = re.compile(
    r"\s+(?:e|ed|and|plus)\s+\d{1,3}\s+"
    r"(?:canzoni|brani|tracce|pezzi|songs|tracks)\b.*$",
    re.IGNORECASE,
)
_CREDIT_SEPARATOR_RE = re.compile(
    r"\s+(?:feat\.?|featuring|with|vs\.?|x)\s+",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ArtistMinimumQuota:
    artist: str
    minimum: int


def user_request_text(prompt: str) -> str:
    """Extract the original user request from internal generation instructions."""
    text = prompt.strip()
    for marker in _REQUEST_MARKERS:
        if marker in text:
            tail = text.split(marker, 1)[1]
            return tail.split("\n", 1)[0].strip()
    return text.split("\n", 1)[0].strip()


def _clean_artist(value: str) -> str:
    cleaned = _TRAILING_CONNECTOR_RE.sub("", " ".join(value.split()))
    return cleaned.strip(" \t\r\n.,;:!?\"'“”")[:180]


def _artist_identity(value: str) -> str:
    """Return a Unicode-safe alphanumeric key independent of punctuation and spacing."""
    decomposed = unicodedata.normalize("NFKD", str(value).casefold())
    return "".join(
        character
        for character in decomposed
        if character.isalnum() and not unicodedata.combining(character)
    )


def _deduplicate_quotas(
    positioned: list[tuple[int, ArtistMinimumQuota]],
) -> list[ArtistMinimumQuota]:
    selected: dict[str, tuple[int, ArtistMinimumQuota]] = {}
    for position, quota in sorted(positioned, key=lambda item: item[0]):
        key = _artist_identity(quota.artist)
        if not key:
            continue
        previous = selected.get(key)
        if previous is None or quota.minimum > previous[1].minimum:
            selected[key] = (position, quota)

    # Defensive final pass: output must never contain two equivalent artist identities.
    result: list[ArtistMinimumQuota] = []
    emitted: set[str] = set()
    for _, quota in sorted(selected.values(), key=lambda item: item[0]):
        key = _artist_identity(quota.artist)
        if key and key not in emitted:
            emitted.add(key)
            result.append(quota)
    return result


def extract_artist_minimum_quotas(prompt: str) -> list[ArtistMinimumQuota]:
    """Extract explicit numeric minimums, preserving one independent quota per artist."""
    request = user_request_text(prompt)
    positions: list[tuple[int, ArtistMinimumQuota]] = []
    for pattern in (_IT_MINIMUM_RE, _EN_MINIMUM_RE):
        for match in pattern.finditer(request):
            artist = _clean_artist(match.group("artist"))
            if not artist:
                continue
            minimum = max(0, min(100, int(match.group("count"))))
            positions.append((match.start(), ArtistMinimumQuota(artist, minimum)))
    return _deduplicate_quotas(positions)


def artist_matches(actual: str, expected: str) -> bool:
    """Match a quota artist exactly, including within explicit collaboration credits."""
    expected_key = _artist_identity(expected)
    if not expected_key:
        return False

    actual_text = str(actual).strip()
    if _artist_identity(actual_text) == expected_key:
        return True

    # Split only explicit collaboration markers. Do not split punctuation such as '/' or
    # '&' because those may be part of a canonical band name (AC/DC, Earth Wind & Fire).
    return any(
        _artist_identity(part) == expected_key
        for part in _CREDIT_SEPARATOR_RE.split(actual_text)
        if part.strip()
    )


def quota_counts(tracks: list[dict[str, Any]], quotas: list[ArtistMinimumQuota]) -> dict[str, int]:
    counts = {quota.artist: 0 for quota in quotas}
    for track in tracks:
        artist = str(track.get("artist", track.get("artists", "")))
        for quota in quotas:
            if artist_matches(artist, quota.artist):
                counts[quota.artist] += 1
    return counts


def quota_deficits(
    tracks: list[dict[str, Any]],
    quotas: list[ArtistMinimumQuota],
) -> list[ArtistMinimumQuota]:
    counts = quota_counts(tracks, quotas)
    return [
        ArtistMinimumQuota(quota.artist, quota.minimum - counts[quota.artist])
        for quota in quotas
        if counts[quota.artist] < quota.minimum
    ]


def quota_guidance(quotas: list[ArtistMinimumQuota]) -> str:
    if not quotas:
        return ""
    requirements = "; ".join(
        f"at least {quota.minimum} tracks by {quota.artist}" for quota in quotas
    )
    return (
        "\n\nPER-ARTIST QUOTAS: the following are independent mandatory minimums, not "
        f"one combined quota: {requirements}. Satisfy every artist minimum separately. "
        "Do not count a track toward a different artist's quota."
    )
