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
    r"[,;]\s*(?=(?:(?:almeno|minimo|min\.|at\s+least|minimum(?:\s+of)?|"
    r"au\s+moins|al\s+menos|m[ií]nimo|como\s+m[ií]nimo|mindestens)\s+)?"
    r"\d{1,3}\s+(?:canzoni|brani|tracce|pezzi|songs|tracks|"
    r"chansons?|titres?|morceaux|canciones|temas?|pistas?|"
    r"lieder[n]?|titel|st[uü]cke)\b)",
    re.IGNORECASE,
)

_IT_TRACK_WORDS = r"(?:canzoni|brani|tracce|pezzi)"
_EN_TRACK_WORDS = r"(?:songs|tracks)"
_FR_TRACK_WORDS = r"(?:chansons?|titres?|morceaux)"
_ES_TRACK_WORDS = r"(?:canciones|temas?|pistas?)"
_DE_TRACK_WORDS = r"(?:lieder[n]?|titel|songs?|st[uü]cke)"
_SHORT_TRACK_WORDS = (
    r"(?:songs?|tracks?|canzoni|brani|tracce|pezzi|canciones|temas?|"
    r"chansons?|titres?|lieder[n]?|titel)"
)
_NEXT_QUOTA_RE = (
    r"(?=\s+(?:e|ed|and|plus|et|y|und)\s+"
    r"(?:(?:almeno|minimo|min\.|at\s+least|minimum(?:\s+of)?|"
    r"au\s+moins|al\s+menos|m[ií]nimo|como\s+m[ií]nimo|mindestens)\s+)?"
    r"\d{1,3}\s+"
    r"(?:(?:canzoni|brani|tracce|pezzi|songs|tracks|chansons?|titres?|morceaux|"
    r"canciones|temas?|pistas?|lieder[n]?|titel|st[uü]cke)\b|"
    r"(?:by|from|di|dei|degli|delle|da|dagli|dalle|de|von)\b)"
    r"|$)"
)

_IT_MINIMUM_RE = re.compile(
    r"(?:\b(?:almeno|minimo|min\.)\s+)?"
    r"(?P<count>\d{1,3})\s+"
    rf"(?:{_IT_TRACK_WORDS}\s*)?"
    r"(?:devono?\s+essere\s+|(?:devono?\s+)?provenire\s+da\s+)?"
    r"(?:di|dei|degli|delle|da|dagli|dalle)\s+"
    rf"(?P<artist>[^,;.!\n]+?){_NEXT_QUOTA_RE}",
    re.IGNORECASE,
)

_EN_MINIMUM_RE = re.compile(
    r"(?:\b(?:at\s+least|minimum(?:\s+of)?)\s+)?"
    r"(?P<count>\d{1,3})\s+"
    rf"(?:{_EN_TRACK_WORDS}\s+)?(?:must\s+be\s+)?(?:by|from)\s+"
    rf"(?P<artist>[^,;.!\n]+?){_NEXT_QUOTA_RE}",
    re.IGNORECASE,
)

_FR_MINIMUM_RE = re.compile(
    r"(?:\b(?:au\s+moins|minimum(?:\s+de)?)\s+)?"
    r"(?P<count>\d{1,3})\s+"
    rf"(?:{_FR_TRACK_WORDS}\s+)?"
    r"(?:doivent\s+(?:être|etre|provenir\s+de)\s+)?"
    r"de\s+"
    rf"(?P<artist>[^,;.!\n]+?){_NEXT_QUOTA_RE}",
    re.IGNORECASE,
)

_ES_MINIMUM_RE = re.compile(
    r"(?:\b(?:al\s+menos|m[ií]nimo(?:\s+de)?|como\s+m[ií]nimo)\s+)?"
    r"(?P<count>\d{1,3})\s+"
    rf"(?:{_ES_TRACK_WORDS}\s+)?"
    r"(?:deben\s+(?:ser|provenir\s+de)\s+)?"
    r"de\s+"
    rf"(?P<artist>[^,;.!\n]+?){_NEXT_QUOTA_RE}",
    re.IGNORECASE,
)

_DE_MINIMUM_RE = re.compile(
    r"(?:\b(?:mindestens|minimum(?:\s+von)?)\s+)?"
    r"(?P<count>\d{1,3})\s+"
    rf"(?:{_DE_TRACK_WORDS}\s+)?"
    r"(?:m[uü]ssen\s+von\s+)?"
    r"von\s+"
    rf"(?P<artist>[^,;.!\n]+?){_NEXT_QUOTA_RE}",
    re.IGNORECASE,
)

_SHORTHAND_QUOTA_CONTEXT_RE = re.compile(
    r"\b(?:must\s+(?:have|contain|include)|should\s+(?:have|contain|include)|"
    r"needs?\s+to\s+(?:have|contain|include)|with|containing|contains?|includes?|"
    r"add|insert|require|requires|"
    r"deve\s+(?:avere|contenere|includere)|devono\s+(?:esserci|essere)|con|"
    r"contiene|contenere|includi|includere|aggiungi|inserisci|"
    r"debe\s+(?:tener|contener|incluir)|con|incluye|agrega|añade|anade|"
    r"doit\s+(?:avoir|contenir|inclure)|avec|contient|inclut|ajoute|"
    r"muss\s+(?:haben|enthalten)|mit|enthält|enthaelt|füge|fuege)\b",
    re.IGNORECASE,
)
_EXACT_SHORTHAND_CONTEXT_RE = re.compile(
    r"\b(?:must\s+(?:have|contain|include)|needs?\s+to\s+(?:have|contain|include)|"
    r"contains?|requires?|"
    r"deve\s+(?:avere|contenere|includere)|deve\s+contenere|contiene|"
    r"debe\s+(?:tener|contener|incluir)|contiene|"
    r"doit\s+(?:avoir|contenir|inclure)|contient|"
    r"muss\s+(?:haben|enthalten)|enthält|enthaelt)\b",
    re.IGNORECASE,
)
_SHORTHAND_PAIR_RE = re.compile(
    rf"\b(?P<count>\d{{1,3}})\s+(?P<artist>[^,;.!?\n]+?)"
    rf"(?=\s*(?:,\s*\d{{1,3}}\s+|"
    rf"\s+(?:and|plus|e|ed|y|et|und)\s+\d{{1,3}}\s+|"
    rf"\s+{_SHORT_TRACK_WORDS}\b))",
    re.IGNORECASE,
)
_SHORT_TRACK_PRESENT_RE = re.compile(rf"\b{_SHORT_TRACK_WORDS}\b", re.IGNORECASE)

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


@dataclass(frozen=True, slots=True)
class ArtistExactQuota:
    artist: str
    count: int


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


def _shorthand_pairs(request: str) -> list[tuple[int, str, int]]:
    if not _SHORT_TRACK_PRESENT_RE.search(request):
        return []
    positioned: list[tuple[int, str, int]] = []
    for match in _SHORTHAND_PAIR_RE.finditer(request):
        artist = _clean_artist(match.group("artist"))
        if not artist:
            continue
        count = max(0, min(100, int(match.group("count"))))
        positioned.append((match.start(), artist, count))
    return positioned if len(positioned) >= 2 else []


def _shorthand_quota_matches(request: str) -> list[tuple[int, ArtistMinimumQuota]]:
    """Parse compact independent counts such as `2 Metallica, 2 Queen tracks`."""
    if not _SHORTHAND_QUOTA_CONTEXT_RE.search(request):
        return []
    return [
        (position, ArtistMinimumQuota(artist, count))
        for position, artist, count in _shorthand_pairs(request)
    ]


def extract_artist_exact_quotas(prompt: str) -> list[ArtistExactQuota]:
    """Extract compact final exact counts when wording explicitly fixes playlist contents."""
    request = user_request_text(prompt)
    if not _EXACT_SHORTHAND_CONTEXT_RE.search(request):
        return []

    selected: list[ArtistExactQuota] = []
    for _, artist, count in _shorthand_pairs(request):
        existing_index = next(
            (
                index
                for index, existing in enumerate(selected)
                if _artists_equivalent(existing.artist, artist)
            ),
            None,
        )
        if existing_index is None:
            selected.append(ArtistExactQuota(artist, count))
            continue
        if selected[existing_index].count == count:
            continue
        # Conflicting exact counts are intentionally not guessed here; the semantic prompt
        # assessment remains responsible for surfacing an ambiguous/impossible request.
        return []
    return selected


def extract_artist_minimum_quotas(prompt: str) -> list[ArtistMinimumQuota]:
    """Extract explicit numeric minimums, preserving one independent quota per artist."""
    request = _QUOTA_CLAUSE_SEPARATOR_RE.sub(" e ", user_request_text(prompt))
    positions: list[tuple[int, ArtistMinimumQuota]] = []
    for pattern in (
        _IT_MINIMUM_RE,
        _EN_MINIMUM_RE,
        _FR_MINIMUM_RE,
        _ES_MINIMUM_RE,
        _DE_MINIMUM_RE,
    ):
        for match in pattern.finditer(request):
            artist = _clean_artist(match.group("artist"))
            if not artist:
                continue
            minimum = max(0, min(100, int(match.group("count"))))
            positions.append((match.start(), ArtistMinimumQuota(artist, minimum)))
    positions.extend(_shorthand_quota_matches(request))
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


def exact_quota_counts(
    tracks: list[dict[str, Any]],
    quotas: list[ArtistExactQuota],
) -> dict[str, int]:
    minimums = [ArtistMinimumQuota(quota.artist, quota.count) for quota in quotas]
    return quota_counts(tracks, minimums)


def exact_quota_mismatches(
    tracks: list[dict[str, Any]],
    quotas: list[ArtistExactQuota],
) -> list[tuple[ArtistExactQuota, int]]:
    counts = exact_quota_counts(tracks, quotas)
    return [
        (quota, counts[quota.artist])
        for quota in quotas
        if counts[quota.artist] != quota.count
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


def exact_quota_guidance(quotas: list[ArtistExactQuota]) -> str:
    if not quotas:
        return ""
    requirements = "; ".join(
        f"exactly {quota.count} tracks by {quota.artist}" for quota in quotas
    )
    return (
        "\n\nEXACT PER-ARTIST COUNTS: these are independent mandatory final counts: "
        f"{requirements}. Do not return more or fewer tracks for any named artist. "
        "These exact counts override any generic quota safety margin for the same artist."
    )
