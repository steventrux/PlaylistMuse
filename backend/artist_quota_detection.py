"""Deterministic extraction and checking of per-artist playlist quotas."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.text_normalization import normalize_identity

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
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


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
    """Collapse punctuation-only spelling variants such as AC/DC and AC-DC."""
    return _NON_ALNUM_RE.sub("", normalize_identity(value))


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

    selected: dict[str, tuple[int, ArtistMinimumQuota]] = {}
    for position, quota in sorted(positions, key=lambda item: item[0]):
        key = _artist_identity(quota.artist)
        if not key:
            continue
        previous = selected.get(key)
        if previous is None or quota.minimum > previous[1].minimum:
            selected[key] = (position, quota)

    return [
        quota
        for _, quota in sorted(selected.values(), key=lambda item: item[0])
    ]


def artist_matches(actual: str, expected: str) -> bool:
    actual_key = _artist_identity(actual)
    expected_key = _artist_identity(expected)
    return bool(expected_key) and expected_key in actual_key


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
