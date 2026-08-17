from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import backend.youtube as youtube
from backend.generation_stage_timing import reset_stage_timings, stage_timings_snapshot


def _candidate(index: int) -> dict[str, str]:
    return {
        "artist": f"Artist {index}",
        "title": f"Song {index}",
        "description": f"Description {index}",
        "reason": f"Reason {index}",
    }


def _track(index: int) -> dict[str, object]:
    return {
        "video_id": f"video-{index}",
        "title": f"Song {index}",
        "artists": f"Artist {index}",
        "album": "Album",
        "duration": "3:00",
        "thumbnail_url": None,
        "url": f"https://music.youtube.com/watch?v=video-{index}",
        "match_score": 100.0,
    }


def test_youtube_cache_round_trip_and_negative_entry(tmp_path: Path):
    cache = tmp_path / "youtube.sqlite3"
    exclusions = {
        "exclude_live": True,
        "exclude_covers": True,
        "exclude_remixes": True,
    }
    candidate = _candidate(1)

    youtube._write_youtube_cache(candidate, exclusions, _track(1), path=cache)
    hit, restored = youtube._read_youtube_cache(
        candidate,
        exclusions,
        path=cache,
    )

    assert hit is True
    assert restored is not None
    assert restored["video_id"] == "video-1"

    missing = _candidate(2)
    youtube._write_youtube_cache(missing, exclusions, None, path=cache)
    hit, restored = youtube._read_youtube_cache(
        missing,
        exclusions,
        path=cache,
    )

    assert hit is True
    assert restored is None


def test_cache_key_changes_with_exclusion_options():
    candidate = _candidate(1)
    strict = {
        "exclude_live": True,
        "exclude_covers": True,
        "exclude_remixes": True,
    }
    permissive = {**strict, "exclude_live": False}

    assert youtube._youtube_cache_key(candidate, strict) != youtube._youtube_cache_key(
        candidate,
        permissive,
    )


def test_resolve_candidates_uses_bounded_parallelism_and_preserves_order(monkeypatch):
    candidates = [_candidate(index) for index in range(8)]
    active = 0
    peak = 0
    lock = threading.Lock()

    async def bypass_metadata(items):
        return list(items), []

    def fake_resolve(candidate, exclusions):
        nonlocal active, peak
        index = int(candidate["title"].split()[-1])
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.04)
        with lock:
            active -= 1
        track = _track(index)
        track["description"] = candidate["description"]
        track["reason"] = candidate["reason"]
        return track

    monkeypatch.setattr(youtube, "_metadata_filter", bypass_metadata)
    monkeypatch.setattr(youtube, "_resolve_one", fake_resolve)
    monkeypatch.setenv("YOUTUBE_RESOLUTION_CONCURRENCY", "3")

    resolved, unresolved = asyncio.run(
        youtube.resolve_candidates(
            candidates,
            {
                "exclude_live": True,
                "exclude_covers": True,
                "exclude_remixes": True,
            },
        )
    )

    assert unresolved == []
    assert peak == 3
    assert [track["video_id"] for track in resolved] == [
        f"video-{index}" for index in range(8)
    ]


def test_resolve_candidates_records_separate_youtube_and_metadata_stage_timings(
    monkeypatch,
):
    candidates = [_candidate(1)]

    async def bypass_metadata(items):
        return list(items), []

    def fake_resolve(candidate, exclusions):
        index = int(candidate["title"].split()[-1])
        return _track(index)

    monkeypatch.setattr(youtube, "_metadata_filter", bypass_metadata)
    monkeypatch.setattr(youtube, "_resolve_one", fake_resolve)

    async def scenario():
        reset_stage_timings()
        await youtube.resolve_candidates(
            candidates,
            {"exclude_live": True, "exclude_covers": True, "exclude_remixes": True},
        )
        return stage_timings_snapshot()

    snapshot = asyncio.run(scenario())

    assert "youtube_resolution" in snapshot
    assert "metadata_validation" in snapshot
    assert snapshot["youtube_resolution"] >= 0
    assert snapshot["metadata_validation"] >= 0


def test_concurrency_setting_is_clamped(monkeypatch):
    monkeypatch.setenv("YOUTUBE_RESOLUTION_CONCURRENCY", "99")
    assert youtube._youtube_resolution_concurrency() == 8

    monkeypatch.setenv("YOUTUBE_RESOLUTION_CONCURRENCY", "0")
    assert youtube._youtube_resolution_concurrency() == 1

    monkeypatch.setenv("YOUTUBE_RESOLUTION_CONCURRENCY", "invalid")
    assert (
        youtube._youtube_resolution_concurrency()
        == youtube.DEFAULT_YOUTUBE_RESOLUTION_CONCURRENCY
    )
