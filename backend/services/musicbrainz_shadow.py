"""Optional background MusicBrainz enrichment that never changes API responses."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

from backend.config import DATA_DIR
from backend.metadata.musicbrainz_decision import with_musicbrainz_decision
from backend.metadata.musicbrainz_policy import (
    PolicyAwareMusicBrainzClient,
    normalize_exclusions,
)

LOGGER = logging.getLogger(__name__)
DEFAULT_SAMPLE_SIZE = 5
MAX_SAMPLE_SIZE = 10
MAX_LOOKUP_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (1.0, 2.0)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def musicbrainz_shadow_enabled() -> bool:
    """Return whether MusicBrainz shadow collection is explicitly enabled."""
    return _truthy(os.getenv("PLAYLISTMUSE_MUSICBRAINZ_SHADOW"))


def musicbrainz_shadow_sample_size() -> int:
    raw = os.getenv("PLAYLISTMUSE_MUSICBRAINZ_SHADOW_SAMPLE", "").strip()
    try:
        value = int(raw) if raw else DEFAULT_SAMPLE_SIZE
    except ValueError:
        value = DEFAULT_SAMPLE_SIZE
    return max(1, min(MAX_SAMPLE_SIZE, value))


def musicbrainz_shadow_path() -> Path:
    configured = os.getenv("PLAYLISTMUSE_MUSICBRAINZ_SHADOW_PATH", "").strip()
    return Path(configured) if configured else DATA_DIR / "musicbrainz-shadow.ndjson"


def _duration_ms(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parts = [int(part) for part in text.split(":")]
    except ValueError:
        return None
    if len(parts) == 2:
        minutes, seconds = parts
        total_seconds = minutes * 60 + seconds
    elif len(parts) == 3:
        hours, minutes, seconds = parts
        total_seconds = hours * 3600 + minutes * 60 + seconds
    else:
        return None
    if min(parts) < 0 or seconds >= 60 or (len(parts) == 3 and minutes >= 60):
        return None
    return total_seconds * 1000


def _snapshot_tracks(tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for track in tracks:
        title = str(track.get("title", "")).strip()
        artists = str(track.get("artists", "")).strip()
        if not title or not artists:
            continue
        snapshot: dict[str, Any] = {
            "video_id": track.get("video_id"),
            "title": title,
            "artists": artists,
        }
        duration = str(track.get("duration", "")).strip()
        duration_ms = _duration_ms(duration)
        if duration:
            snapshot["duration"] = duration
        if duration_ms is not None:
            snapshot["duration_ms"] = duration_ms
        snapshots.append(snapshot)
    return snapshots


def _append_record(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        handle.write("\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _task_finished(task: asyncio.Task[Any]) -> None:
    _BACKGROUND_TASKS.discard(task)
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        LOGGER.warning("MusicBrainz shadow task failed: %s", error)


def _accepts_exclusions(search_track: Callable[..., Any]) -> bool:
    """Preserve compatibility with simple test and integration clients."""
    try:
        parameters = inspect.signature(search_track).parameters.values()
    except (TypeError, ValueError):
        return True
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        or parameter.name == "exclusions"
        for parameter in parameters
    )


def _retryable(error: Exception) -> bool:
    if isinstance(error, httpx.TransportError):
        return True
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in RETRYABLE_STATUS_CODES
    return False


async def _lookup_with_retry(
    client: Any,
    track: dict[str, Any],
    exclusions: dict[str, bool],
    *,
    sleep_fn: Callable[[float], Any] = asyncio.sleep,
) -> tuple[dict[str, Any] | None, int, Exception | None]:
    kwargs: dict[str, Any] = {"duration_ms": track.get("duration_ms")}
    if _accepts_exclusions(client.search_track):
        kwargs["exclusions"] = exclusions

    for attempt in range(1, MAX_LOOKUP_ATTEMPTS + 1):
        try:
            match = await client.search_track(
                track["title"],
                track["artists"],
                **kwargs,
            )
            return match, attempt, None
        except Exception as error:  # Shadow mode must never affect the user flow.
            if attempt >= MAX_LOOKUP_ATTEMPTS or not _retryable(error):
                return None, attempt, error
            await sleep_fn(RETRY_DELAYS_SECONDS[attempt - 1])

    raise AssertionError("unreachable")


async def run_musicbrainz_shadow(
    tracks: list[dict[str, Any]],
    *,
    options: Any = None,
    client_factory: Callable[[], Any] = PolicyAwareMusicBrainzClient,
    output_path: Path | None = None,
    sample_size: int | None = None,
    sleep_fn: Callable[[float], Any] = asyncio.sleep,
) -> dict[str, Any]:
    """Collect policy-aware metadata and append one private NDJSON record."""
    selected = _snapshot_tracks(tracks)[: sample_size or musicbrainz_shadow_sample_size()]
    exclusions = normalize_exclusions(options)
    results: list[dict[str, Any]] = []

    async with client_factory() as client:
        for track in selected:
            raw_match, attempts, error = await _lookup_with_retry(
                client,
                track,
                exclusions,
                sleep_fn=sleep_fn,
            )
            if error is None:
                match = with_musicbrainz_decision(raw_match, exclusions)
                results.append(
                    {
                        "input": track,
                        "musicbrainz": match,
                        "attempts": attempts,
                    }
                )
                continue

            LOGGER.info(
                "MusicBrainz shadow lookup failed for %s — %s after %s attempt(s): %s",
                track["artists"],
                track["title"],
                attempts,
                error,
            )
            results.append(
                {
                    "input": track,
                    "musicbrainz": None,
                    "error": type(error).__name__,
                    "attempts": attempts,
                }
            )

    decisions = [
        item["musicbrainz"].get("decision")
        for item in results
        if isinstance(item.get("musicbrainz"), dict)
    ]
    payload = {
        "schema_version": 3,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "track_count": len(tracks),
        "sampled_count": len(selected),
        "exclusions": exclusions,
        "matched_count": decisions.count("matched"),
        "ambiguous_count": decisions.count("ambiguous"),
        "rejected_count": decisions.count("rejected"),
        "error_count": sum(1 for item in results if item.get("error")),
        "results": results,
    }
    await asyncio.to_thread(_append_record, output_path or musicbrainz_shadow_path(), payload)
    return payload


def schedule_musicbrainz_shadow(
    tracks: list[dict[str, Any]],
    options: Any = None,
) -> bool:
    """Schedule shadow enrichment with the playlist's live/remix/cover policy."""
    if not musicbrainz_shadow_enabled():
        return False

    snapshots = _snapshot_tracks(tracks)
    if not snapshots:
        return False

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False

    task = loop.create_task(run_musicbrainz_shadow(snapshots, options=options))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_task_finished)
    return True
