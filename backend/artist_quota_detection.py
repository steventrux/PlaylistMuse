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
_QUOTA_CLAUSE_SEPARATOR_RE = re.compile(
    r"[,;]\s*(?=(?:(?:almeno|minimo|min\.|at\s+least|minimum(?:\s+of)?)\s+)?"
    r"\d{1,3}\s+(?:canzoni|brani|tracce|pezzi|songs|tracks)\b)",
    re.IGNORECASE,
)

_IT_TRACK_WORDS = r"(?:canzoni|brani|tracce|pezzi)"
_EN_TRACK_WORDS = r"(?:songs|tracks)"
_NEXT_QUOTA_RE = (
    r"(?=\s+(?:e|ed|and|plus)\s+"
    r"(?:(?:almeno|minimo|min\.|at\s+least|minimum(?:\s+of)?)\s+)?"
    r"\d{1,3}\s+(?:canzoni|brani|tracce|pezzi|songs|tracks)\b|$)"
)

_IT_MINIMUM_RE = re.compile(
    r"(?:\b(?:almeno|minimo|min\.)\s+)?"
    r"(?P<count>\d{1,3})\s+"
    rf"{_IT_TRACK_WORDS}\s*"
    r"(?:devono?\s+essere\s+|(?:devono?\s+)?provenire\s+da\s+)?"
    r"(?:di|dei|degli|delle|da|dagli|dalle)\s+"
    rf"(?P<artist>[^,;.!\n]+?){_NEXT_QUOTA_RE}",
    re.IGNORECASE,
)

_EN_MINIMUM_RE = re.compile(
    r"(?:\b(?:at\s+least|minimum(?:\s+of)?)\s+)?"
    r"(?P<count>\d{1,3})\s+"
    rf"{_EN_TRACK_WORDS}\s+(?:must\s+be\s+)?(?:by|from)\s+"
    rf"(?P<artist>[^,;.!\n]+?){_NEXT_QUOTA_RE}",
    re.IGNORECASE,
)

_CREDIT_SEPARATOR_RE = re.compile(
    r"\s+(?:feat\.?|featuring|with|vs\.?|x)\s+",
    re.IGNORECASE,
)
_LEADING_ARTICLE_RE = re.compile(
    r"^(?:the|i|gli|le|la|il|lo|les|los|las|die|der|das)\s+",
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
    return " ".join(value.split()).strip(" \t\r\n.,;:!?\"'“”")[:180]


def _artist_identity(value: str) -> str:
    """Return a Unicode-safe alphanumeric key independent of punctuation and spacing."""
    decomposed = unicodedata.normalize("NFKD", str(value).casefold())
    return "".join(
        character
        for character in decomposed
        if character.isalnum() and not unicodedata.combining(character)
    )


def _artist_identity_variants(value: str) -> set[str]:
    """Return exact identities, optionally ignoring a leading grammatical article."""
    text = " ".join(str(value).split()).strip()
    variants = {_artist_identity(text)}
    without_article = _LEADING_ARTICLE_RE.sub("", text, count=1).strip()
    if without_article and without_article != text:
        variants.add(_artist_identity(without_article))
    return {variant for variant in variants if variant}


def _artists_equivalent(left: str, right: str) -> bool:
    return bool(_artist_identity_variants(left) & _artist_identity_variants(right))


def _deduplicate_quotas(
    positioned: list[tuple[int, ArtistMinimumQuota]],
) -> list[ArtistMinimumQuota]:
    """Keep one quota per equivalent artist, preserving order and the strongest minimum."""
    selected: list[tuple[int, ArtistMinimumQuota]] = []
    for position, quota in sorted(positioned, key=lambda item: item[0]):
        matching_index = next(
            (
                index
                for index, (_, existing) in enumerate(selected)
                if _artists_equivalent(existing.artist, quota.artist)
            ),
            None,
        )
        if matching_index is None:
            selected.append((position, quota))
            continue

        existing_position, existing = selected[matching_index]
        if quota.minimum > existing.minimum:
            selected[matching_index] = (
                min(position, existing_position),
                ArtistMinimumQuota(existing.artist, quota.minimum),
            )

    return [quota for _, quota in sorted(selected, key=lambda item: item[0])]


def extract_artist_minimum_quotas(prompt: str) -> list[ArtistMinimumQuota]:
    """Extract explicit numeric minimums, preserving one independent quota per artist."""
    request = _QUOTA_CLAUSE_SEPARATOR_RE.sub(" e ", user_request_text(prompt))
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
    actual_text = str(actual).strip()
    if _artists_equivalent(actual_text, expected):
        return True

    return any(
        _artists_equivalent(part, expected)
        for part in _CREDIT_SEPARATOR_RE.split(actual_text)
        if part.strip()
    )


def quota_counts(
    tracks: list[dict[str, Any]],
    quotas: list[ArtistMinimumQuota],
) -> dict[str, int]:
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
