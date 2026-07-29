"""Optional background MusicBrainz enrichment that never changes API responses."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from backend.config import DATA_DIR
from backend.metadata.musicbrainz import MusicBrainzClient
from backend.metadata.musicbrainz_decision import with_musicbrainz_decision

LOGGER = logging.getLogger(__name__)
DEFAULT_SAMPLE_SIZE = 5
MAX_SAMPLE_SIZE = 10
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


async def run_musicbrainz_shadow(
    tracks: list[dict[str, Any]],
    *,
    client_factory: Callable[[], Any] = MusicBrainzClient,
    output_path: Path | None = None,
    sample_size: int | None = None,
) -> dict[str, Any]:
    """Collect MusicBrainz metadata for a sample and append one private NDJSON record."""
    selected = _snapshot_tracks(tracks)[: sample_size or musicbrainz_shadow_sample_size()]
    results: list[dict[str, Any]] = []

    async with client_factory() as client:
        for track in selected:
            try:
                raw_match = await client.search_track(
                    track["title"],
                    track["artists"],
                    duration_ms=track.get("duration_ms"),
                )
                match = with_musicbrainz_decision(raw_match)
                results.append({"input": track, "musicbrainz": match})
            except Exception as error:  # Shadow mode must never affect the user flow.
                LOGGER.info(
                    "MusicBrainz shadow lookup failed for %s — %s: %s",
                    track["artists"],
                    track["title"],
                    error,
                )
                results.append(
                    {
                        "input": track,
                        "musicbrainz": None,
                        "error": type(error).__name__,
                    }
                )

    decisions = [
        item["musicbrainz"].get("decision")
        for item in results
        if isinstance(item.get("musicbrainz"), dict)
    ]
    payload = {
        "schema_version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "track_count": len(tracks),
        "sampled_count": len(selected),
        "matched_count": decisions.count("matched"),
        "ambiguous_count": decisions.count("ambiguous"),
        "rejected_count": decisions.count("rejected"),
        "error_count": sum(1 for item in results if item.get("error")),
        "results": results,
    }
    await asyncio.to_thread(_append_record, output_path or musicbrainz_shadow_path(), payload)
    return payload


def schedule_musicbrainz_shadow(tracks: list[dict[str, Any]]) -> bool:
    """Schedule shadow enrichment without delaying or changing playlist generation."""
    if not musicbrainz_shadow_enabled():
        return False

    snapshots = _snapshot_tracks(tracks)
    if not snapshots:
        return False

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False

    task = loop.create_task(run_musicbrainz_shadow(snapshots))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_task_finished)
    return True
