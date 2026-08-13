"""Guard temporal constraints against later re-recordings or artist-credit aliases."""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

import httpx

from backend.metadata_validation import MetadataConstraints, validate_candidate
from backend.musicbrainz_work import recording_work_ids
from backend.text_normalization import normalize_identity
from backend.version import USER_AGENT

_ARTIST_SPLIT_RE = re.compile(r"\s*(?:/|,|&|×|\bx\b|\bfeat\.?\b|\bfeaturing\b|\bwith\b)\s*", re.I)


def _temporal_active(constraints: MetadataConstraints) -> bool:
    return any(
        value is not None
        for value in (
            constraints.release_year,
            constraints.release_year_from,
            constraints.release_year_to,
        )
    )


def _artist_aliases(track: dict[str, Any]) -> list[str]:
    canonical = str(track.get("artists") or track.get("artist") or "").strip()
    requested = str(track.get("requested_artist") or "").strip()
    seen = {normalize_identity(canonical)} if canonical else set()
    aliases: list[str] = []

    def add(value: str) -> None:
        cleaned = " ".join(str(value).split()).strip(" ,/&-")
        key = normalize_identity(cleaned)
        if cleaned and key and key not in seen:
            seen.add(key)
            aliases.append(cleaned)

    add(requested)
    for source in (canonical, requested):
        parts = [part for part in _ARTIST_SPLIT_RE.split(source) if part.strip()]
        for part in parts:
            add(part)
    return aliases[:4]


def _temporal_violation(violations: list[str]) -> bool:
    return any(str(value).casefold().startswith("release year ") for value in violations)


def _metadata_recording_mbid(track: dict[str, Any]) -> str:
    metadata = track.get("metadata_validation")
    if not isinstance(metadata, dict):
        return ""
    return str(metadata.get("recording_mbid") or "").strip()


async def filter_temporal_artist_aliases(
    resolved: list[dict[str, Any]],
    constraints: MetadataConstraints,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Reject a later alias recording only when MusicBrainz confirms the same work.

    Title equality alone is never enough: an earlier recording by another artist is used
    only when both MusicBrainz recording entities point to at least one common work.
    Missing relationships or service failures therefore remain fail-open.
    """
    if not resolved or not _temporal_active(constraints):
        return resolved, []

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(8.0),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    ) as client:
        for track in resolved:
            current_mbid = _metadata_recording_mbid(track)
            aliases = _artist_aliases(track)
            if not current_mbid or not aliases:
                accepted.append(track)
                continue

            current_work_ids = await recording_work_ids(current_mbid, client=client)
            if not current_work_ids:
                accepted.append(track)
                continue

            title = str(track.get("requested_title") or track.get("title") or "").strip()
            confirmed = None
            confirmed_alias = ""
            for alias in aliases:
                alternative = await validate_candidate(
                    {"artist": alias, "title": title},
                    constraints,
                    client=client,
                )
                alt_mbid = str(alternative.metadata.recording_mbid or "").strip()
                if (
                    alternative.status != "invalid"
                    or not _temporal_violation(alternative.violations)
                    or not alt_mbid
                ):
                    continue
                alt_work_ids = await recording_work_ids(alt_mbid, client=client)
                if current_work_ids & alt_work_ids:
                    confirmed = alternative
                    confirmed_alias = alias
                    break

            if confirmed is None:
                accepted.append(track)
                continue

            metadata = asdict(confirmed.metadata)
            warnings = list(metadata.get("warnings") or [])
            warnings.append(
                f"Earlier equivalent recording confirmed via MusicBrainz work relation: {confirmed_alias}"
            )
            metadata["warnings"] = warnings
            rejected.append(
                {
                    "artist": str(track.get("artists") or track.get("artist") or ""),
                    "title": str(track.get("title") or ""),
                    "unresolved_reason": "metadata_validation",
                    "metadata_validation": {
                        "status": confirmed.status,
                        "violations": list(confirmed.violations),
                        **metadata,
                    },
                    "resolved_catalogue": {
                        "title": track.get("title"),
                        "artists": track.get("artists") or track.get("artist"),
                        "video_id": track.get("video_id"),
                    },
                }
            )

    return accepted, rejected
