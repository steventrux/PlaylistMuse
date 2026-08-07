"""Detect and enforce explicit chronological playlist ordering."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Literal

import httpx

from backend.metadata_validation import (
    MIN_MATCH_SCORE,
    USER_AGENT,
    MetadataConstraints,
    TrackMetadata,
    lookup_track_metadata,
    validate_candidate,
)

ChronologicalOrder = Literal["oldest_first", "newest_first"]
_MIN_ORDER_CONFIDENCE = 0.85

_OLDEST_FIRST_PATTERNS = (
    re.compile(r"\b(?:oldest|earliest|older)\b.{0,60}\b(?:newest|latest|newer|recent)\b", re.I),
    re.compile(r"\b(?:old|older)\s+(?:to|through)\s+(?:new|newer)\b", re.I),
    re.compile(r"\bchronological(?:ly|\s+order)?\b", re.I),
    re.compile(r"\bpi[uù]\s+vecchi[aoe]?\b.{0,60}\bpi[uù]\s+recent[ei]?\b", re.I),
    re.compile(r"\b(?:ordine\s+cronologico|cronologicamente)\b", re.I),
    re.compile(r"\bm[aá]s\s+antigu[ao]\b.{0,60}\bm[aá]s\s+reciente\b", re.I),
    re.compile(r"\borden\s+cronol[oó]gico\b", re.I),
    re.compile(r"\bplus\s+ancien(?:ne)?\b.{0,60}\bplus\s+r[eé]cent(?:e)?\b", re.I),
    re.compile(r"\border\s+chronologique\b", re.I),
    re.compile(r"\b(?:aeltest|altest|ältest)\w*\b.{0,60}\b(?:neuest)\w*\b", re.I),
    re.compile(r"\bchronologisch\b", re.I),
    re.compile(r"\bmais\s+antig[ao]\b.{0,60}\bmais\s+recente\b", re.I),
    re.compile(r"\bordem\s+cronol[oó]gica\b", re.I),
)

_NEWEST_FIRST_PATTERNS = (
    re.compile(r"\b(?:newest|latest|newer|recent)\b.{0,60}\b(?:oldest|earliest|older)\b", re.I),
    re.compile(r"\b(?:new|newer)\s+(?:to|through)\s+(?:old|older)\b", re.I),
    re.compile(r"\breverse\s+chronological(?:\s+order)?\b", re.I),
    re.compile(r"\bpi[uù]\s+recent[ei]?\b.{0,60}\bpi[uù]\s+vecchi[aoe]?\b", re.I),
    re.compile(r"\b(?:ordine\s+cronologico\s+inverso|cronologico\s+inverso)\b", re.I),
    re.compile(r"\bm[aá]s\s+reciente\b.{0,60}\bm[aá]s\s+antigu[ao]\b", re.I),
    re.compile(r"\borden\s+cronol[oó]gico\s+inverso\b", re.I),
    re.compile(r"\bplus\s+r[eé]cent(?:e)?\b.{0,60}\bplus\s+ancien(?:ne)?\b", re.I),
    re.compile(r"\border\s+chronologique\s+invers[eé]\b", re.I),
    re.compile(r"\b(?:neuest)\w*\b.{0,60}\b(?:aeltest|altest|ältest)\w*\b", re.I),
    re.compile(r"\bchronologisch\s+r[uü]ckw[aä]rts\b", re.I),
    re.compile(r"\bmais\s+recente\b.{0,60}\bmais\s+antig[ao]\b", re.I),
    re.compile(r"\bordem\s+cronol[oó]gica\s+inversa\b", re.I),
)

_LIVE_BRACKET_SUFFIX_RE = re.compile(
    r"\s*[\[(][^\])]*(?:\blive\b|\bdal\s+vivo\b|\ben\s+vivo\b|\bao\s+vivo\b)[^\])]*[\])]\s*$",
    re.I,
)
_LIVE_DASH_SUFFIX_RE = re.compile(
    r"\s*[-–—]\s*(?:live\b.*|dal\s+vivo\b.*|en\s+vivo\b.*|ao\s+vivo\b.*)$",
    re.I,
)
_LIVE_WORD_SUFFIX_RE = re.compile(
    r"\s+(?:live|dal\s+vivo|en\s+vivo|ao\s+vivo)(?:\s+\d{4})?\s*$",
    re.I,
)
_LIVE_ALBUM_RE = re.compile(
    r"(?:^|\b)(?:live(?:\s+(?:at|from|in)\b)?|dal\s+vivo|en\s+vivo|ao\s+vivo)(?:\b|$)",
    re.I,
)
_REMASTER_BRACKET_SUFFIX_RE = re.compile(
    r"\s*[\[(][^\])]*\bremaster(?:ed)?\b[^\])]*[\])]\s*$",
    re.I,
)
_REMASTER_DASH_SUFFIX_RE = re.compile(
    r"\s*[-–—]\s*(?:\d{4}\s+)?remaster(?:ed)?\b.*$",
    re.I,
)


def _local_chronological_order(prompt: str) -> ChronologicalOrder | None:
    """Fallback for common explicit wording when structured interpretation is unavailable."""
    normalized = " ".join(str(prompt).split())
    if not normalized:
        return None
    # Test inverse forms first because they can also contain the generic chronological wording.
    if any(pattern.search(normalized) for pattern in _NEWEST_FIRST_PATTERNS):
        return "newest_first"
    if any(pattern.search(normalized) for pattern in _OLDEST_FIRST_PATTERNS):
        return "oldest_first"
    return None


def chronological_order_from_payload(
    payload: dict[str, Any] | None,
    prompt: str = "",
) -> ChronologicalOrder | None:
    """Read a trusted language-independent ordering directive with a conservative fallback."""
    if isinstance(payload, dict):
        raw = str(payload.get("chronological_order") or "").strip().casefold()
        if raw in {"oldest_first", "newest_first"}:
            confidence = payload.get("field_confidence")
            try:
                trusted = (
                    isinstance(confidence, dict)
                    and float(confidence.get("chronological_order", 0.0))
                    >= _MIN_ORDER_CONFIDENCE
                )
            except (TypeError, ValueError):
                trusted = False
            if not trusted:
                trusted = str(payload.get("confidence", "")).casefold() == "high"
            if trusted:
                return raw  # type: ignore[return-value]
    return _local_chronological_order(prompt)


def _track_artist(track: dict[str, Any]) -> str:
    return str(track.get("artists") or track.get("artist") or "").strip()


def _track_title(track: dict[str, Any]) -> str:
    return str(track.get("title") or "").strip()


def _is_live_track(track: dict[str, Any]) -> bool:
    """Detect version-style live markers without treating song names such as 'Live Forever' as live."""
    title = _track_title(track)
    album = str(track.get("album") or "").strip()
    return bool(
        _LIVE_BRACKET_SUFFIX_RE.search(title)
        or _LIVE_DASH_SUFFIX_RE.search(title)
        or _LIVE_WORD_SUFFIX_RE.search(title)
        or (album and _LIVE_ALBUM_RE.search(album))
    )


def _strip_live_suffix(title: str) -> str:
    """Return the underlying song title used to find the original release year."""
    cleaned = str(title).strip()
    for pattern in (
        _LIVE_BRACKET_SUFFIX_RE,
        _LIVE_DASH_SUFFIX_RE,
        _LIVE_WORD_SUFFIX_RE,
    ):
        cleaned = pattern.sub("", cleaned).strip(" -–—")
    return cleaned or str(title).strip()


def _strip_remaster_suffix(title: str) -> str:
    cleaned = str(title).strip()
    for pattern in (_REMASTER_BRACKET_SUFFIX_RE, _REMASTER_DASH_SUFFIX_RE):
        cleaned = pattern.sub("", cleaned).strip(" -–—")
    return cleaned or str(title).strip()


def _chronology_lookup_titles(track: dict[str, Any]) -> list[str]:
    """Return conservative metadata lookup titles in preference order.

    A live recording is deliberately resolved only through the underlying song title so its
    concert/live-album year can never become the chronological year. For non-live tracks the
    catalogue title remains primary, with a remaster suffix removed only as a fallback.
    """
    title = _track_title(track)
    if not title:
        return []
    if _is_live_track(track):
        return [_strip_live_suffix(title)]

    variants = [title]
    remasterless = _strip_remaster_suffix(title)
    if remasterless and remasterless.casefold() != title.casefold():
        variants.append(remasterless)
    return variants


def _release_year(metadata: TrackMetadata) -> int | None:
    try:
        if metadata.original_release_year is not None:
            return int(metadata.original_release_year)
        if metadata.original_release_date:
            candidate = str(metadata.original_release_date)[:4]
            return int(candidate) if candidate.isdigit() else None
    except (TypeError, ValueError):
        return None
    return None


def _metadata_has_reliable_year(metadata: TrackMetadata) -> bool:
    return _release_year(metadata) is not None and metadata.match_score >= MIN_MATCH_SCORE


def _embedded_release_year(track: dict[str, Any]) -> int | None:
    # Embedded metadata for a live item may describe the live recording itself. Always resolve
    # the underlying song again so chronology uses the song's original release year.
    if _is_live_track(track):
        return None
    metadata = track.get("metadata_validation")
    if not isinstance(metadata, dict):
        return None
    try:
        score = float(metadata.get("match_score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    confidence = str(metadata.get("confidence") or "").casefold()
    if score < MIN_MATCH_SCORE and confidence not in {"high", "medium"}:
        return None
    year = metadata.get("original_release_year")
    if year is None:
        date = str(metadata.get("original_release_date") or "").strip()
        year = date[:4] if len(date) >= 4 else None
    try:
        parsed = int(year) if year is not None else None
    except (TypeError, ValueError):
        return None
    return parsed if parsed and 1800 <= parsed <= time.gmtime().tm_year else None


async def _lookup_original_release_year(
    track: dict[str, Any],
    *,
    client: httpx.AsyncClient,
) -> int | None:
    """Resolve an original song year with a direct historical probe as a safe fallback."""
    artist = _track_artist(track)
    if not artist:
        return None

    broad_constraints = MetadataConstraints(
        release_year_from=1800,
        release_year_to=time.gmtime().tm_year,
    )
    for title in _chronology_lookup_titles(track):
        metadata = await lookup_track_metadata(artist, title, client=client)
        if _metadata_has_reliable_year(metadata):
            return _release_year(metadata)

        # A stale/negative cache entry or an initially weak MusicBrainz match must not make a
        # well-known song unverifiable. validate_candidate triggers the existing direct
        # historical MusicBrainz probe for this broad range and refreshes reliable metadata.
        validation = await validate_candidate(
            {"artist": artist, "title": title},
            broad_constraints,
            client=client,
        )
        if _metadata_has_reliable_year(validation.metadata):
            return _release_year(validation.metadata)
    return None


async def order_tracks_by_release_date(
    tracks: list[dict[str, Any]],
    direction: ChronologicalOrder | None,
) -> list[dict[str, Any]]:
    """Return tracks ordered by verified original song release year.

    Chronology deliberately uses the first publication year of the underlying song. A live
    version therefore inherits the original song's year, never the concert, live-album or
    YouTube upload year. When only year precision is available, tracks from the same year keep
    their current relative order.
    """
    if direction is None or len(tracks) < 2:
        return list(tracks)

    years: list[int | None] = [_embedded_release_year(track) for track in tracks]
    pending = [index for index, year in enumerate(years) if year is None]

    if pending:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(8.0),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        ) as client:
            results = await asyncio.gather(
                *(
                    _lookup_original_release_year(tracks[index], client=client)
                    for index in pending
                )
            )
        for index, year in zip(pending, results, strict=True):
            years[index] = year

    missing = [
        f"{_track_artist(track)} — {_track_title(track)}".strip(" —")
        for track, year in zip(tracks, years, strict=True)
        if year is None
    ]
    if missing:
        sample = "; ".join(missing[:4])
        suffix = "" if len(missing) <= 4 else f"; +{len(missing) - 4} more"
        raise ValueError(
            "PlaylistMuse could not verify the original release year for every track required "
            f"by the chronological ordering: {sample}{suffix}."
        )

    decorated = [
        (int(year), dict(track))
        for track, year in zip(tracks, years, strict=True)
        if year is not None
    ]
    decorated.sort(
        key=lambda item: item[0],
        reverse=direction == "newest_first",
    )
    return [track for _, track in decorated]
