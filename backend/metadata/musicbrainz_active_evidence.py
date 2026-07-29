"""Strong MusicBrainz evidence used only by the opt-in active filter."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping

from rapidfuzz import fuzz

from backend.metadata.musicbrainz import (
    _artist_credit,
    _date_year,
    _lucene_quote,
    _rate_limited_get,
)

_STRONG_TERMS: dict[str, tuple[str, ...]] = {
    "live": ("live", "in concert"),
    "remix": ("remix", "dj mix", "12 inch mix", "12\" mix"),
    "cover": ("cover", "karaoke", "tribute"),
}
_MIN_ARTIST_SCORE = 90.0
_MIN_SEARCH_SCORE = 90.0
_MIN_TITLE_TOKENS_WITHOUT_WORK = 3
_MIN_YEAR_GAP_WITH_WORK = 1
_MIN_YEAR_GAP_WITHOUT_WORK = 3


def _normalize(value: Any) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or "").casefold())
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(part for part in re.split(r"[\W_]+", without_marks) if part)


def _contains_term(text: str, term: str) -> bool:
    normalized_text = _normalize(text)
    normalized_term = _normalize(term)
    if not normalized_text or not normalized_term:
        return False
    pattern = rf"(?<!\w){re.escape(normalized_term)}(?!\w)"
    return re.search(pattern, normalized_text) is not None


def strong_version_categories(match: Mapping[str, Any] | None) -> list[str]:
    """Return only evidence strong enough to remove a resolved track.

    Release titles and release-group secondary types are intentionally excluded:
    they describe the release container and can misclassify an otherwise normal track.
    """
    if not isinstance(match, Mapping):
        return []

    categories: list[str] = []
    for value in match.get("relationship_version_categories") or []:
        category = str(value).strip().casefold()
        if category in _STRONG_TERMS and category not in categories:
            categories.append(category)

    text = " ".join(
        (
            str(match.get("recording_title", "")),
            str(match.get("recording_disambiguation", "")),
        )
    )
    for category, terms in _STRONG_TERMS.items():
        if category in categories:
            continue
        if any(_contains_term(text, term) for term in terms):
            categories.append(category)
    return categories


def _history_entry(recording: Mapping[str, Any], input_title: str) -> dict[str, Any] | None:
    title = str(recording.get("title", "")).strip()
    if not title or _normalize(title) != _normalize(input_title):
        return None

    artist_text, artists = _artist_credit(dict(recording))
    year = _date_year(recording.get("first-release-date"))
    if not artist_text or year is None:
        return None

    try:
        search_score = float(recording.get("score", 0) or 0)
    except (TypeError, ValueError):
        search_score = 0.0

    return {
        "recording_mbid": str(recording.get("id", "")).strip() or None,
        "recording_title": title,
        "artists": artist_text,
        "artist_mbids": [
            str(item.get("mbid", "")).strip()
            for item in artists
            if str(item.get("mbid", "")).strip()
        ],
        "first_release_year": year,
        "search_score": round(search_score, 1),
    }


async def _search_history(client: Any, query: str, title: str) -> list[dict[str, Any]]:
    response = await _rate_limited_get(
        client,
        params={"query": query, "fmt": "json", "limit": 100},
    )
    response.raise_for_status()
    payload = response.json()
    recordings = payload.get("recordings") if isinstance(payload, Mapping) else None
    if not isinstance(recordings, list):
        return []

    entries: list[dict[str, Any]] = []
    for recording in recordings:
        if not isinstance(recording, Mapping):
            continue
        entry = _history_entry(recording, title)
        if entry is not None:
            entries.append(entry)
    return entries


async def search_title_history(client: Any, title: str) -> list[dict[str, Any]]:
    """Search exact-title recordings across all artists."""
    query = f"recording:{_lucene_quote(str(title).strip())}"
    return await _search_history(client, query, title)


async def search_artist_title_history(
    client: Any,
    title: str,
    artists: str,
) -> list[dict[str, Any]]:
    """Search exact-title recordings for the current artist only."""
    query = (
        f"recording:{_lucene_quote(str(title).strip())} AND "
        f"artistname:{_lucene_quote(str(artists).strip())}"
    )
    return await _search_history(client, query, title)


def infer_cover_from_history(
    match: Mapping[str, Any] | None,
    *,
    title: str,
    artists: str,
    history: list[dict[str, Any]],
    current_artist_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Infer a cover only when an exact-title different artist clearly predates it.

    Active filtering supplies a dedicated title-and-current-artist search. This prevents
    a later remaster or compilation date from making the original performer look newer
    than another artist. If that dedicated search has no reliable current-artist date,
    the active filter fails open and does not infer a cover.
    """
    if not isinstance(match, Mapping):
        return None

    current_pool = history if current_artist_history is None else current_artist_history
    current_entries = [
        item
        for item in current_pool
        if float(item.get("search_score", 0.0) or 0.0) >= _MIN_SEARCH_SCORE
        and fuzz.token_set_ratio(artists, str(item.get("artists", "")))
        >= _MIN_ARTIST_SCORE
    ]
    current_years = [
        int(item["first_release_year"])
        for item in current_entries
        if item.get("first_release_year") is not None
    ]

    if current_artist_history is not None and not current_years:
        return None

    fallback_year = match.get("effective_release_year")
    try:
        current_year = min(current_years) if current_years else int(fallback_year)
    except (TypeError, ValueError):
        return None

    has_work_evidence = bool(match.get("work_relationships"))
    title_token_count = len(_normalize(title).split())
    if not has_work_evidence and title_token_count < _MIN_TITLE_TOKENS_WITHOUT_WORK:
        return None

    minimum_gap = (
        _MIN_YEAR_GAP_WITH_WORK if has_work_evidence else _MIN_YEAR_GAP_WITHOUT_WORK
    )
    older_candidates: list[dict[str, Any]] = []
    for item in history:
        if float(item.get("search_score", 0.0) or 0.0) < _MIN_SEARCH_SCORE:
            continue
        if fuzz.token_set_ratio(artists, str(item.get("artists", ""))) >= _MIN_ARTIST_SCORE:
            continue
        try:
            candidate_year = int(item.get("first_release_year"))
        except (TypeError, ValueError):
            continue
        if current_year - candidate_year < minimum_gap:
            continue
        older_candidates.append(item)

    if not older_candidates:
        return None

    earliest = min(older_candidates, key=lambda item: int(item["first_release_year"]))
    return {
        "basis": "exact_title_earlier_different_artist",
        "title": title,
        "current_artists": artists,
        "current_earliest_year": current_year,
        "current_year_source": (
            "artist_title_search" if current_artist_history is not None else "title_history"
        ),
        "earlier_recording_mbid": earliest.get("recording_mbid"),
        "earlier_artists": earliest.get("artists"),
        "earlier_year": earliest.get("first_release_year"),
        "year_gap": current_year - int(earliest["first_release_year"]),
        "work_relationship_present": has_work_evidence,
    }


async def infer_cover_evidence(
    client: Any,
    match: Mapping[str, Any] | None,
    source: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Fetch current-artist and cross-artist chronology for conservative evidence."""
    raw_client = getattr(client, "_client", client)
    title = str(source.get("title", "")).strip()
    artists = str(source.get("artists", "")).strip()
    if not title or not artists:
        return None

    current_artist_history = await search_artist_title_history(raw_client, title, artists)
    if not current_artist_history:
        return None

    history = await search_title_history(raw_client, title)
    return infer_cover_from_history(
        match,
        title=title,
        artists=artists,
        history=history,
        current_artist_history=current_artist_history,
    )
