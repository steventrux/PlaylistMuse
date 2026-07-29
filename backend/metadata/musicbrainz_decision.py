"""Conservative decisions for MusicBrainz shadow-match diagnostics."""

from __future__ import annotations

from typing import Any

from backend.metadata.musicbrainz_policy import normalize_exclusions

SAFE_VERSION_PENALTY = 10.0
SAFE_DURATION_DELTA_MS = 15_000
AMBIGUOUS_LEXICAL_THRESHOLD = 90.0


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def classify_musicbrainz_match(
    match: Any,
    exclusions: Any = None,
) -> dict[str, Any]:
    """Return a conservative matched/ambiguous/rejected decision.

    Live, remix and cover conflicts follow the same options selected for the
    playlist. Other alternate versions and large duration mismatches remain
    conservative because PlaylistMuse has no dedicated option for them.
    """
    if not isinstance(match, dict) or not match.get("recording_mbid"):
        return {
            "decision": "rejected",
            "safe_match": False,
            "ambiguous": False,
            "decision_reasons": ["no_recording_candidate"],
        }

    active = normalize_exclusions(exclusions or match.get("active_exclusions"))
    lexical_score = _number(
        match.get("lexical_score"),
        100.0 if match.get("matched") else 0.0,
    )
    version_penalty = _number(match.get("version_penalty"))
    categories = {
        str(value).strip().casefold()
        for value in (match.get("version_categories") or [])
        if str(value).strip()
    }
    duration_delta = match.get("duration_delta_ms")
    try:
        duration_delta_ms = int(duration_delta) if duration_delta is not None else None
    except (TypeError, ValueError):
        duration_delta_ms = None

    conflicts: list[str] = []
    if "live" in categories and active["exclude_live"]:
        conflicts.append("excluded_live")
    if "remix" in categories and active["exclude_remixes"]:
        conflicts.append("excluded_remix")
    if "cover" in categories and active["exclude_covers"]:
        conflicts.append("excluded_cover")
    if "alternate" in categories:
        conflicts.append("alternate_version")
    if not categories and version_penalty > SAFE_VERSION_PENALTY:
        conflicts.append("alternate_version")
    if duration_delta_ms is not None and duration_delta_ms > SAFE_DURATION_DELTA_MS:
        conflicts.append("duration_mismatch")
    if lexical_score < AMBIGUOUS_LEXICAL_THRESHOLD:
        conflicts.append("title_or_artist_mismatch")

    if match.get("matched") is True and not conflicts:
        return {
            "decision": "matched",
            "safe_match": True,
            "ambiguous": False,
            "decision_reasons": [],
        }

    if lexical_score >= AMBIGUOUS_LEXICAL_THRESHOLD:
        reasons = conflicts or ["insufficient_confidence"]
        return {
            "decision": "ambiguous",
            "safe_match": False,
            "ambiguous": True,
            "decision_reasons": reasons,
        }

    return {
        "decision": "rejected",
        "safe_match": False,
        "ambiguous": False,
        "decision_reasons": conflicts or ["insufficient_evidence"],
    }


def with_musicbrainz_decision(
    match: Any,
    exclusions: Any = None,
) -> dict[str, Any] | None:
    """Copy one MusicBrainz result and attach its conservative decision."""
    if not isinstance(match, dict):
        return None
    return {**match, **classify_musicbrainz_match(match, exclusions)}
