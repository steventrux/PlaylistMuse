"""Conservative decisions for MusicBrainz shadow-match diagnostics."""

from __future__ import annotations

from typing import Any

SAFE_VERSION_PENALTY = 10.0
SAFE_DURATION_DELTA_MS = 15_000
AMBIGUOUS_LEXICAL_THRESHOLD = 90.0


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def classify_musicbrainz_match(match: Any) -> dict[str, Any]:
    """Return a conservative matched/ambiguous/rejected decision.

    The MusicBrainz client's raw ``matched`` flag is necessary but not sufficient:
    shadow analysis also refuses alternate versions and large duration mismatches.
    """
    if not isinstance(match, dict) or not match.get("recording_mbid"):
        return {
            "decision": "rejected",
            "safe_match": False,
            "ambiguous": False,
            "decision_reasons": ["no_recording_candidate"],
        }

    lexical_score = _number(match.get("lexical_score"), 100.0 if match.get("matched") else 0.0)
    version_penalty = _number(match.get("version_penalty"))
    duration_delta = match.get("duration_delta_ms")
    try:
        duration_delta_ms = int(duration_delta) if duration_delta is not None else None
    except (TypeError, ValueError):
        duration_delta_ms = None

    conflicts: list[str] = []
    if version_penalty > SAFE_VERSION_PENALTY:
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


def with_musicbrainz_decision(match: Any) -> dict[str, Any] | None:
    """Copy one MusicBrainz result and attach its conservative decision."""
    if not isinstance(match, dict):
        return None
    return {**match, **classify_musicbrainz_match(match)}
