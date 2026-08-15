"""Pure YouTube Music matching and recording-variant helpers."""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from backend.youtube_title_normalization import base_title

_TITLE_TOKEN_RE = re.compile(r"[a-z0-9]+")
_LIVE_RE = re.compile(r"(?:\blive(?=\b|\d)|\b(?:concert|session)\b)")
_REMIX_RE = re.compile(r"\b(remix|mix|edit|mashup)\b")
_COVER_RE = re.compile(
    r"\b(cover|tribute|karaoke)\b"
    r"|\bin\s+the\s+style\s+of\b"
    r"|\b(?:as\s+)?made\s+famous\s+by\b"
    r"|\boriginally\s+(?:performed|recorded)\s+by\b"
)


def title_score(candidate_title: str, result_title: str) -> float:
    """Score normalized titles while ignoring case, punctuation and collaborator credits."""
    candidate_tokens_list = _TITLE_TOKEN_RE.findall(base_title(candidate_title).casefold())
    result_tokens_list = _TITLE_TOKEN_RE.findall(base_title(result_title).casefold())
    candidate_tokens = set(candidate_tokens_list)
    result_tokens = set(result_tokens_list)
    extra_tokens = max(0, len(result_tokens - candidate_tokens))
    penalty = min(28, extra_tokens * 2.5)
    candidate = " ".join(candidate_tokens_list)
    result = " ".join(result_tokens_list)
    return max(0.0, fuzz.token_set_ratio(candidate, result) - penalty)


def _marker_terms(pattern: re.Pattern[str], value: str) -> set[str]:
    return {match.group(0).casefold() for match in pattern.finditer(str(value).casefold())}


def _added_marker(
    pattern: re.Pattern[str],
    requested_value: str,
    observed_value: str,
) -> bool:
    """Return true only when observed metadata adds an unrequested marker."""
    requested = _marker_terms(pattern, requested_value)
    observed = _marker_terms(pattern, observed_value)
    return bool(observed - requested)


def exclusion_reason(
    title: str,
    *,
    album: str = "",
    artists: str = "",
    candidate_title: str = "",
    candidate_artists: str = "",
    live: bool,
    covers: bool,
    remixes: bool,
) -> str | None:
    """Reject only recording-variant markers added by the catalogue result."""
    if live and (
        _added_marker(_LIVE_RE, candidate_title, title)
        or _added_marker(_LIVE_RE, candidate_title, album)
    ):
        return "excluded_live"
    if remixes and (
        _added_marker(_REMIX_RE, candidate_title, title)
        or _added_marker(_REMIX_RE, candidate_title, album)
    ):
        return "excluded_remix"
    if covers and (
        _added_marker(_COVER_RE, candidate_title, title)
        or _added_marker(_COVER_RE, candidate_title, album)
        or _added_marker(_COVER_RE, candidate_artists, artists)
    ):
        return "excluded_cover"
    return None
