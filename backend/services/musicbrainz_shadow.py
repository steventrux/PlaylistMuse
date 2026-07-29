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


def _snapshot_tracks(tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "video_id": track.get("video_id"),
            "title": str(track.get("title", "")).strip(),
            "artists": str(track.get("artists", "")).strip(),
        }
        for track in tracks
        if str(track.get("title", "")).strip()
        and str(track.get("artists", "")).strip()
    ]


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
                match = await client.search_track(track["title"], track["artists"])
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

    payload = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "track_count": len(tracks),
        "sampled_count": len(selected),
        "matched_count": sum(
            1
            for item in results
            if isinstance(item.get("musicbrainz"), dict)
            and item["musicbrainz"].get("matched") is True
        ),
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
