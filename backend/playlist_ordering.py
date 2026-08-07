"""Detect and enforce explicit chronological playlist ordering."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Literal

import httpx

from backend.metadata_validation import (
    MIN_MATCH_SCORE,
    USER_AGENT,
    lookup_track_metadata,
)
from backend.text_normalization import normalize_identity

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


def _date_key(value: str) -> tuple[int, int, int]:
    parts = str(value).split("-")
    result: list[int] = []
    for index in range(3):
        try:
            result.append(int(parts[index]) if index < len(parts) else 1)
        except ValueError:
            result.append(1)
    return result[0], result[1], result[2]


def _embedded_release_date(track: dict[str, Any]) -> str | None:
    metadata = track.get("metadata_validation")
    if not isinstance(metadata, dict):
        return None
    value = str(metadata.get("original_release_date") or "").strip()
    if not value:
        year = metadata.get("original_release_year")
        try:
            value = str(int(year)) if year is not None else ""
        except (TypeError, ValueError):
            value = ""
    if not value:
        return None
    try:
        score = float(metadata.get("match_score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    confidence = str(metadata.get("confidence") or "").casefold()
    if score < MIN_MATCH_SCORE and confidence not in {"high", "medium"}:
        return None
    return value


async def order_tracks_by_release_date(
    tracks: list[dict[str, Any]],
    direction: ChronologicalOrder | None,
) -> list[dict[str, Any]]:
    """Return tracks ordered by verified original release date.

    The first-release date is used, never a YouTube upload, remaster or reissue date. If an
    explicit chronological request cannot be fully verified, fail rather than silently return
    an order that only looks chronological.
    """
    if direction is None or len(tracks) < 2:
        return list(tracks)

    dates: dict[str, str] = {}
    pending: dict[str, tuple[str, str]] = {}
    for track in tracks:
        artist = _track_artist(track)
        title = _track_title(track)
        key = f"{normalize_identity(artist)}::{normalize_identity(title)}"
        embedded = _embedded_release_date(track)
        if embedded:
            dates[key] = embedded
        elif artist and title and key not in pending:
            pending[key] = (artist, title)

    if pending:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(8.0),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        ) as client:
            async def lookup(key: str, artist: str, title: str) -> tuple[str, str | None]:
                metadata = await lookup_track_metadata(artist, title, client=client)
                if (
                    metadata.original_release_date
                    and metadata.match_score >= MIN_MATCH_SCORE
                ):
                    return key, metadata.original_release_date
                return key, None

            results = await asyncio.gather(
                *(lookup(key, artist, title) for key, (artist, title) in pending.items())
            )
        for key, release_date in results:
            if release_date:
                dates[key] = release_date

    missing: list[str] = []
    decorated: list[tuple[tuple[int, int, int], int, dict[str, Any]]] = []
    for index, track in enumerate(tracks):
        artist = _track_artist(track)
        title = _track_title(track)
        key = f"{normalize_identity(artist)}::{normalize_identity(title)}"
        release_date = dates.get(key)
        if not release_date:
            missing.append(f"{artist} — {title}".strip(" —"))
            continue
        decorated.append((_date_key(release_date), index, track))

    if missing:
        sample = "; ".join(missing[:4])
        suffix = "" if len(missing) <= 4 else f"; +{len(missing) - 4} more"
        raise ValueError(
            "PlaylistMuse could not verify the original release date for every track required "
            f"by the chronological ordering: {sample}{suffix}."
        )

    reverse = direction == "newest_first"
    decorated.sort(key=lambda item: item[0], reverse=reverse)
    return [dict(item[2]) for item in decorated]
