"""Optional MusicBrainz validation of resolved YouTube Music tracks."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from backend.config import DATA_DIR
from backend.metadata.musicbrainz_active_evidence import (
    infer_cover_evidence,
    strong_version_categories,
)
from backend.metadata.musicbrainz_decision import with_musicbrainz_decision
from backend.metadata.musicbrainz_policy import (
    PolicyAwareMusicBrainzClient,
    normalize_exclusions,
)
from backend.services.musicbrainz_shadow import (
    MAX_LOOKUP_ATTEMPTS,
    RETRY_DELAYS_SECONDS,
    _duration_ms,
    _lookup_with_retry,
    _retryable,
)

LOGGER = logging.getLogger(__name__)
_ALL_ALLOWED = {
    "exclude_live": False,
    "exclude_covers": False,
    "exclude_remixes": False,
}


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def musicbrainz_active_filter_enabled() -> bool:
    """Return whether synchronous MusicBrainz exclusion validation is enabled."""
    return _truthy(os.getenv("PLAYLISTMUSE_MUSICBRAINZ_ACTIVE_FILTER"))


def musicbrainz_active_filter_path() -> Path:
    configured = os.getenv("PLAYLISTMUSE_MUSICBRAINZ_ACTIVE_PATH", "").strip()
    return Path(configured) if configured else DATA_DIR / "musicbrainz-active.ndjson"


def _snapshot(track: dict[str, Any]) -> dict[str, Any] | None:
    title = str(track.get("title", "")).strip()
    artists = str(track.get("artists", "")).strip()
    if not title or not artists:
        return None
    result: dict[str, Any] = {
        "video_id": track.get("video_id"),
        "title": title,
        "artists": artists,
    }
    duration = str(track.get("duration", "")).strip()
    if duration:
        result["duration"] = duration
        duration_ms = _duration_ms(duration)
        if duration_ms is not None:
            result["duration_ms"] = duration_ms
    return result


def _blocked_categories(
    categories: list[str],
    exclusions: dict[str, bool],
) -> list[str]:
    normalized = {str(value).strip().casefold() for value in categories if str(value).strip()}
    blocked: list[str] = []
    if "live" in normalized and exclusions["exclude_live"]:
        blocked.append("live")
    if "cover" in normalized and exclusions["exclude_covers"]:
        blocked.append("cover")
    if "remix" in normalized and exclusions["exclude_remixes"]:
        blocked.append("remix")
    return blocked


def _append_record(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        handle.write("\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass


async def _cover_evidence_with_retry(
    client: Any,
    match: dict[str, Any] | None,
    source: dict[str, Any],
    *,
    evidence_fn: Callable[..., Any],
    sleep_fn: Callable[[float], Any],
) -> tuple[dict[str, Any] | None, int, Exception | None]:
    for attempt in range(1, MAX_LOOKUP_ATTEMPTS + 1):
        try:
            evidence = await evidence_fn(client, match, source)
            return evidence, attempt, None
        except Exception as error:
            if attempt >= MAX_LOOKUP_ATTEMPTS or not _retryable(error):
                return None, attempt, error
            await sleep_fn(RETRY_DELAYS_SECONDS[attempt - 1])
    raise AssertionError("unreachable")


async def filter_musicbrainz_tracks(
    tracks: list[dict[str, Any]],
    exclusions: Any,
    *,
    client_factory: Callable[[], Any] = PolicyAwareMusicBrainzClient,
    output_path: Path | None = None,
    sleep_fn: Callable[[float], Any] = asyncio.sleep,
    cover_evidence_fn: Callable[..., Any] = infer_cover_evidence,
    force: bool | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Remove tracks only when MusicBrainz provides strong exclusion evidence.

    MusicBrainz is queried with all version families allowed so ranking cannot hide a
    cover, live recording or remix merely because the user selected its exclusion.
    Release-level labels remain diagnostic only: active removal requires recording or
    relationship evidence. When explicit cover attributes are missing, an exact-title
    chronology check may infer a cover from a clearly earlier different artist.
    Lookup failures and missing metadata fail open and never break playlist creation.
    """
    enabled = musicbrainz_active_filter_enabled() if force is None else force
    active = normalize_exclusions(exclusions)
    if not enabled or not tracks or not any(active.values()):
        return list(tracks), []

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    async with client_factory() as client:
        for track in tracks:
            source = _snapshot(track)
            if source is None:
                accepted.append(track)
                continue

            raw_match, attempts, error = await _lookup_with_retry(
                client,
                source,
                _ALL_ALLOWED,
                sleep_fn=sleep_fn,
            )
            if error is not None:
                accepted.append(track)
                results.append(
                    {
                        "input": source,
                        "musicbrainz": None,
                        "active_version_categories": [],
                        "blocked_categories": [],
                        "accepted": True,
                        "error": type(error).__name__,
                        "attempts": attempts,
                    }
                )
                LOGGER.info(
                    "MusicBrainz active validation failed open for %s — %s after %s attempt(s): %s",
                    source["artists"],
                    source["title"],
                    attempts,
                    error,
                )
                continue

            match = with_musicbrainz_decision(raw_match, _ALL_ALLOWED)
            active_categories = strong_version_categories(match)
            cover_evidence: dict[str, Any] | None = None
            cover_evidence_attempts = 0
            cover_evidence_error: Exception | None = None

            if (
                active["exclude_covers"]
                and "cover" not in active_categories
                and isinstance(match, dict)
            ):
                (
                    cover_evidence,
                    cover_evidence_attempts,
                    cover_evidence_error,
                ) = await _cover_evidence_with_retry(
                    client,
                    match,
                    source,
                    evidence_fn=cover_evidence_fn,
                    sleep_fn=sleep_fn,
                )
                if cover_evidence is not None:
                    active_categories.append("cover")
                elif cover_evidence_error is not None:
                    LOGGER.info(
                        "MusicBrainz cover chronology failed open for %s — %s after %s attempt(s): %s",
                        source["artists"],
                        source["title"],
                        cover_evidence_attempts,
                        cover_evidence_error,
                    )

            blocked = _blocked_categories(active_categories, active)
            is_accepted = not blocked
            if isinstance(match, dict):
                match = {
                    **match,
                    "active_version_categories": active_categories,
                    "active_policy_excluded_categories": blocked,
                    "active_cover_evidence": cover_evidence,
                    "active_decision": "accepted" if is_accepted else "blocked",
                }

            (accepted if is_accepted else rejected).append(track)
            result: dict[str, Any] = {
                "input": source,
                "musicbrainz": match,
                "active_version_categories": active_categories,
                "blocked_categories": blocked,
                "accepted": is_accepted,
                "attempts": attempts,
                "cover_evidence_attempts": cover_evidence_attempts,
            }
            if cover_evidence_error is not None:
                result["cover_evidence_error"] = type(cover_evidence_error).__name__
            results.append(result)

    payload = {
        "schema_version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "track_count": len(tracks),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "error_count": sum(1 for item in results if item.get("error")),
        "cover_evidence_error_count": sum(
            1 for item in results if item.get("cover_evidence_error")
        ),
        "exclusions": active,
        "results": results,
    }
    await asyncio.to_thread(
        _append_record,
        output_path or musicbrainz_active_filter_path(),
        payload,
    )
    return accepted, rejected
