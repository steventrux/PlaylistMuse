"""Local-only aggregate statistics computed from the playlist library.

Nothing here is sent anywhere -- it only reads what is already stored on disk to
answer "what has this installation generated so far". `general` covers music-taste
data (genres, artists, moods, periods); `nerd` covers technical data (AI provider
usage, generation timing, error counts). Provider, duration and error data only
exist for playlists/failures recorded after that tracking was added, so anything
lacking it is reported as "unknown" rather than assumed.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from collections import Counter
from typing import Any

from backend.generation_counter import generations_by_month, total_generations
from backend.generation_errors import error_breakdown
from backend.playlist_library import DATABASE_PATH


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH, timeout=5)
    connection.row_factory = sqlite3.Row
    return connection


def _decode(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _top(counter: Counter[str]) -> list[dict[str, Any]]:
    """Every distinct value, ranked by count -- the frontend truncates for its
    "top 5" overview and shows this full list on the dedicated detail page."""
    return [{"label": label, "count": count} for label, count in counter.most_common()]


def _stage_timings_summary(
    durations_by_stage: dict[str, list[int]],
) -> dict[str, dict[str, Any]]:
    return {
        stage: {
            "avg_ms": round(statistics.fmean(values)),
            "median_ms": round(statistics.median(values)),
            "p95_ms": _percentile(values, 95),
            "sample_size": len(values),
        }
        for stage, values in durations_by_stage.items()
    }


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(percentile / 100 * (len(ordered) - 1))))
    return ordered[index]


def compute_stats() -> dict[str, Any]:
    """Read the whole library once and aggregate every dimension in one pass."""
    rows: list[sqlite3.Row] = []
    if DATABASE_PATH.exists():
        with _connect() as connection:
            rows = connection.execute(
                "SELECT status, track_count, playlist_json, created_at FROM playlists"
            ).fetchall()

    genres: Counter[str] = Counter()
    moods: Counter[str] = Counter()
    periods: Counter[str] = Counter()
    artists: Counter[str] = Counter()
    providers: Counter[str] = Counter()

    published = 0
    tagged = 0
    durations_ms: list[int] = []
    durations_by_stage: dict[str, list[int]] = {}
    track_counts: list[int] = []

    for row in rows:
        playlist = _decode(row["playlist_json"])

        tags = playlist.get("tags")
        if isinstance(tags, dict):
            genre_list = tags.get("genre") or []
            mood_list = tags.get("mood") or []
            period_list = tags.get("period") or []
            if genre_list or mood_list or period_list:
                tagged += 1
            genres.update(str(value) for value in genre_list if value)
            moods.update(str(value) for value in mood_list if value)
            periods.update(str(value) for value in period_list if value)

        for track in playlist.get("tracks") or []:
            if not isinstance(track, dict):
                continue
            raw_artists = str(track.get("artists", "")).strip()
            for artist in (name.strip() for name in raw_artists.split(",")):
                if artist:
                    artists[artist] += 1

        meta = playlist.get("generation_meta")
        provider = "unknown"
        if isinstance(meta, dict):
            provider = str(meta.get("provider") or "").strip() or "unknown"
            duration = meta.get("duration_ms")
            if isinstance(duration, int | float) and duration >= 0:
                durations_ms.append(int(duration))
            stage_timings = meta.get("stage_timings_ms")
            if isinstance(stage_timings, dict):
                for stage, stage_duration in stage_timings.items():
                    if isinstance(stage_duration, int | float) and stage_duration >= 0:
                        durations_by_stage.setdefault(str(stage), []).append(
                            int(stage_duration)
                        )
        providers[provider] += 1

        if row["status"] == "published":
            published += 1
        track_counts.append(int(row["track_count"] or 0))

    saved = len(rows)

    errors = error_breakdown()

    return {
        "general": {
            "total_generated": total_generations(),
            "total_saved": saved,
            "total_published": published,
            "top_genres": _top(genres),
            "top_artists": _top(artists),
            "top_moods": _top(moods),
            "top_periods": _top(periods),
            "playlists_by_month": dict(sorted(generations_by_month().items())),
        },
        "nerd": {
            "provider_breakdown": dict(providers),
            "avg_generation_ms": (
                round(statistics.fmean(durations_ms)) if durations_ms else None
            ),
            "median_generation_ms": (
                round(statistics.median(durations_ms)) if durations_ms else None
            ),
            "p95_generation_ms": _percentile(durations_ms, 95),
            "duration_sample_size": len(durations_ms),
            "stage_timings": _stage_timings_summary(durations_by_stage),
            "avg_track_count": (
                round(statistics.fmean(track_counts), 1) if track_counts else None
            ),
            "tag_coverage_percent": round(100 * tagged / saved, 1) if saved else None,
            "draft_vs_published": {"draft": saved - published, "published": published},
            "error_breakdown": errors,
            "total_errors": sum(errors.values()),
        },
    }
