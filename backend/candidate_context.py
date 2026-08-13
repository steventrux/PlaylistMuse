"""Preserve candidate identity and apply context-aware recording checks."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from backend.recording_variants import (
    RecordingVariantPolicy,
    recording_variant_violations,
)
from backend.youtube_matching import exclusion_reason, title_score

MIN_CONTEXT_TITLE_SCORE = 70.0


def _candidate_artist(candidate: dict[str, Any]) -> str:
    return str(candidate.get("artist") or candidate.get("artists") or "").strip()


def _track_artist(track: dict[str, Any]) -> str:
    return str(track.get("artists") or track.get("artist") or "").strip()


def _origin_signature(item: dict[str, Any]) -> tuple[str, str]:
    return (
        str(item.get("description") or "").strip(),
        str(item.get("reason") or "").strip(),
    )


def _origin_score(
    track: dict[str, Any],
    candidate: dict[str, Any],
    *,
    artist_matches: Any,
) -> float:
    """Reuse catalogue title/artist semantics to recover the originating request."""
    track_signature = _origin_signature(track)
    candidate_signature = _origin_signature(candidate)
    if all(track_signature) and track_signature == candidate_signature:
        return 1_000.0

    if not artist_matches(_track_artist(track), _candidate_artist(candidate)):
        return -1.0
    score = title_score(
        str(candidate.get("title") or ""),
        str(track.get("title") or ""),
    )
    return score if score >= MIN_CONTEXT_TITLE_SCORE else -1.0


def annotate_resolved_candidate_context(
    resolved: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    *,
    artist_matches: Any,
) -> list[dict[str, Any]]:
    """Attach the exact requested identity and soft Recco metadata to resolved tracks."""
    annotated: list[dict[str, Any]] = []
    for track in resolved:
        copy = dict(track)
        scored = [
            (
                _origin_score(copy, item, artist_matches=artist_matches),
                item,
            )
            for item in candidates
            if isinstance(item, dict)
        ]
        candidate = max(scored, key=lambda item: item[0], default=(-1.0, None))[1]
        if candidate is not None and _origin_score(
            copy,
            candidate,
            artist_matches=artist_matches,
        ) >= 0.0:
            copy["requested_artist"] = _candidate_artist(candidate)
            copy["requested_title"] = str(candidate.get("title") or "").strip()
            for key in ("popularity", "reccobeats_id", "source"):
                value = candidate.get(key)
                if value not in (None, ""):
                    copy[key] = value
        annotated.append(copy)
    return annotated


def _excluded_variant_reason(
    track: dict[str, Any],
    policy: RecordingVariantPolicy,
) -> str | None:
    if not policy.excluded:
        return None
    return exclusion_reason(
        str(track.get("title") or ""),
        album=str(track.get("album") or ""),
        artists=_track_artist(track),
        candidate_title=str(track.get("requested_title") or track.get("title") or ""),
        candidate_artists=str(track.get("requested_artist") or _track_artist(track)),
        live="live" in policy.excluded,
        covers="cover" in policy.excluded,
        remixes="remix" in policy.excluded,
    )


def filter_resolved_recording_variants_contextual(
    resolved: list[dict[str, Any]],
    policy: RecordingVariantPolicy,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate positive recording requirements and contextual exclusions.

    Exclusions are evaluated against the originally requested title/artist so a song
    whose canonical title happens to contain a variant-like word is not mistaken for
    an alternate recording. Positive requirements retain the existing semantic validator.
    """
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    required_only = replace(policy, included=frozenset(), excluded=frozenset())

    for track in resolved:
        violations = recording_variant_violations([track], required_only)
        excluded_reason = _excluded_variant_reason(track, policy)
        if excluded_reason:
            violations.append(excluded_reason)
        if not violations:
            accepted.append(track)
            continue
        rejected.append(
            {
                "artist": _track_artist(track),
                "title": str(track.get("title") or ""),
                "unresolved_reason": "recording_variant_validation",
                "recording_variant_violations": violations,
            }
        )
    return accepted, rejected
