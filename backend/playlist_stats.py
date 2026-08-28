"""Local-only aggregate statistics computed from the playlist library.

Nothing here is sent anywhere -- it only reads what is already stored on disk to
answer "what has this installation generated so far". `general` covers music-taste
data (genres, artists, moods, periods, personal tags); `nerd` covers technical data (generation
timing, prompt complexity, track/tag coverage, error counts), broken down per AI provider so each
provider's own effectiveness can be judged separately rather than blended into one
average. Provider, duration and error data only exist for playlists/failures
recorded after that tracking was added, so anything lacking it is reported under
the "unknown" provider rather than assumed.
"""

from __future__ import annotations

import json
import re
import sqlite3
import statistics
from collections import Counter
from typing import Any

from backend.generation_counter import generations_by_month, total_generations
from backend.generation_errors import error_breakdown
from backend.playlist_library import DATABASE_PATH, split_artist_credit

_DECADE_RE = re.compile(r"^\d{3,4}0s$")

# Stage names generation code can currently emit via record_stage_ms()/_log_stage()
# (see backend/generation_runtime_core.py, backend/generation_runtime.py,
# backend/main.py, backend/youtube.py). Older saved playlists can carry stage keys
# from a since-removed feature (e.g. "journey_ordering" from the retired Track
# Journey mode) baked into their persisted generation_meta -- those are real
# historical facts about how that specific playlist was generated, so the data is
# never deleted, but a stage nothing can produce anymore has no reason to keep
# surfacing in the aggregate "AI performance" stats. Filtered at aggregation time,
# not at the source, so it stays a display concern rather than data loss.
_CURRENT_GENERATION_STAGES = frozenset(
    {
        "llm_initial",
        "llm_replacement",
        "llm_replenishment",
        "llm_guided",
        "lastfm_prompt_discovery",
        "lastfm_seed_discovery",
        "catalogue_resolution",
        "energy_ordering",
        "youtube_resolution",
        "metadata_validation",
        # Not produced by record_stage_ms() call sites today (grepped), but kept
        # recognized: the frontend's STAGE_LABELS already has a friendly label for
        # it and existing tests use it as the canonical initial-draft stage example.
        "ai_draft",
    }
)


def _normalize_tag(value: str) -> str:
    """Fold casing variants (e.g. "energetic" / "Energetic") into one label."""
    return value.strip().title()


def _expand_period(value: str) -> list[str]:
    """Split a combined range like "1970s-1980s" into its individual decades.

    Only splits when every hyphen-separated part actually looks like a decade
    (e.g. "1970s") -- anything else (a single decade, or a value that merely
    contains a hyphen) is returned unchanged.
    """
    text = value.strip()
    if not text:
        return []
    parts = [part.strip() for part in text.split("-")]
    if len(parts) > 1 and all(_DECADE_RE.match(part) for part in parts):
        return parts
    return [text]


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


def _new_provider_bucket() -> dict[str, Any]:
    return {
        "playlist_count": 0,
        "published": 0,
        "tagged": 0,
        "durations_ms": [],
        "durations_by_stage": {},
        "track_counts": [],
        "complexity_scores": [],
    }


def _bucket_stats(bucket: dict[str, Any], errors: dict[str, int]) -> dict[str, Any]:
    saved = bucket["playlist_count"]
    return {
        "playlist_count": saved,
        "avg_generation_ms": (
            round(statistics.fmean(bucket["durations_ms"]))
            if bucket["durations_ms"]
            else None
        ),
        "median_generation_ms": (
            round(statistics.median(bucket["durations_ms"]))
            if bucket["durations_ms"]
            else None
        ),
        "p95_generation_ms": _percentile(bucket["durations_ms"], 95),
        "duration_sample_size": len(bucket["durations_ms"]),
        "stage_timings": _stage_timings_summary(bucket["durations_by_stage"]),
        "avg_track_count": (
            round(statistics.fmean(bucket["track_counts"]), 1)
            if bucket["track_counts"]
            else None
        ),
        "avg_complexity_score": (
            round(statistics.fmean(bucket["complexity_scores"]), 1)
            if bucket["complexity_scores"]
            else None
        ),
        "tag_coverage_percent": (
            round(100 * bucket["tagged"] / saved, 1) if saved else None
        ),
        "draft_vs_published": {
            "draft": saved - bucket["published"],
            "published": bucket["published"],
        },
        "error_breakdown": errors,
        "total_errors": sum(errors.values()),
    }


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
    custom_tags: Counter[str] = Counter()
    by_provider: dict[str, dict[str, Any]] = {}

    published_total = 0
    for row in rows:
        playlist = _decode(row["playlist_json"])

        tags = playlist.get("tags")
        tagged_row = False
        if isinstance(tags, dict):
            genre_list = tags.get("genre") or []
            mood_list = tags.get("mood") or []
            period_list = tags.get("period") or []
            custom_list = tags.get("custom") or []
            if genre_list or mood_list or period_list:
                tagged_row = True
            genres.update(_normalize_tag(str(value)) for value in genre_list if value)
            moods.update(_normalize_tag(str(value)) for value in mood_list if value)
            for value in period_list:
                if value:
                    periods.update(_expand_period(str(value)))
            custom_tags.update(_normalize_tag(str(value)) for value in custom_list if value)

        for track in playlist.get("tracks") or []:
            if not isinstance(track, dict):
                continue
            raw_artists = str(track.get("artists", "")).strip()
            for artist in split_artist_credit(raw_artists):
                artists[artist] += 1

        meta = playlist.get("generation_meta")
        provider = "unknown"
        duration: Any = None
        stage_timings: Any = None
        complexity_score: Any = None
        if isinstance(meta, dict):
            provider = str(meta.get("provider") or "").strip() or "unknown"
            duration = meta.get("duration_ms")
            stage_timings = meta.get("stage_timings_ms")
            complexity_score = meta.get("complexity_score")

        bucket = by_provider.setdefault(provider, _new_provider_bucket())
        bucket["playlist_count"] += 1
        if tagged_row:
            bucket["tagged"] += 1
        if isinstance(duration, int | float) and duration >= 0:
            bucket["durations_ms"].append(int(duration))
        if isinstance(stage_timings, dict):
            for stage, stage_duration in stage_timings.items():
                if str(stage) not in _CURRENT_GENERATION_STAGES:
                    continue
                if isinstance(stage_duration, int | float) and stage_duration >= 0:
                    bucket["durations_by_stage"].setdefault(str(stage), []).append(
                        int(stage_duration)
                    )
        if isinstance(complexity_score, int | float) and 0 <= complexity_score <= 100:
            bucket["complexity_scores"].append(complexity_score)
        if row["status"] == "published":
            bucket["published"] += 1
            published_total += 1
        bucket["track_counts"].append(int(row["track_count"] or 0))

    saved = len(rows)
    errors_by_provider = error_breakdown()

    provider_stats: dict[str, dict[str, Any]] = {}
    for provider in set(by_provider) | set(errors_by_provider):
        bucket = by_provider.get(provider) or _new_provider_bucket()
        errors = errors_by_provider.get(provider, {})
        provider_stats[provider] = _bucket_stats(bucket, errors)

    all_bucket = _new_provider_bucket()
    all_errors: Counter[str] = Counter()
    for bucket in by_provider.values():
        all_bucket["playlist_count"] += bucket["playlist_count"]
        all_bucket["published"] += bucket["published"]
        all_bucket["tagged"] += bucket["tagged"]
        all_bucket["durations_ms"].extend(bucket["durations_ms"])
        all_bucket["track_counts"].extend(bucket["track_counts"])
        all_bucket["complexity_scores"].extend(bucket["complexity_scores"])
        for stage, values in bucket["durations_by_stage"].items():
            all_bucket["durations_by_stage"].setdefault(stage, []).extend(values)
    for errors in errors_by_provider.values():
        all_errors.update(errors)
    totals_stats = _bucket_stats(all_bucket, dict(all_errors))

    return {
        "general": {
            "total_generated": total_generations(),
            "total_saved": saved,
            "total_published": published_total,
            "top_genres": _top(genres),
            "top_artists": _top(artists),
            "top_moods": _top(moods),
            "top_periods": _top(periods),
            "top_custom_tags": _top(custom_tags),
            "playlists_by_month": dict(sorted(generations_by_month().items())),
        },
        "nerd": {
            "totals": totals_stats,
            "by_provider": provider_stats,
        },
    }
