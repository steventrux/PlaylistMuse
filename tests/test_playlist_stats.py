from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import backend.generation_counter as generation_counter
import backend.generation_errors as generation_errors
import backend.playlist_stats as playlist_stats
from backend.playlist_library import PlaylistLibrary


def _playlist(
    *,
    name: str,
    artists: list[str],
    tags: dict[str, list[str]] | None = None,
    generation_meta: dict[str, object] | None = None,
    youtube: bool = False,
) -> dict:
    playlist: dict = {
        "name": name,
        "description": "",
        "prompt": "",
        "tracks": [
            {"title": f"Track {index}", "artists": artist}
            for index, artist in enumerate(artists)
        ],
    }
    if tags is not None:
        playlist["tags"] = tags
    if generation_meta is not None:
        playlist["generation_meta"] = generation_meta
    if youtube:
        playlist["youtube_playlist"] = {
            "id": "yt-1",
            "url": "https://music.youtube.com/playlist?list=yt-1",
        }
    return playlist


def _seed_library(database_path: Path) -> PlaylistLibrary:
    library = PlaylistLibrary(database_path)
    library.create(_playlist(
        name="Synth Drive",
        artists=["Tame Impala", "MGMT"],
        tags={"genre": ["Synthwave"], "mood": ["Dreamy"], "period": ["1980s"]},
        generation_meta={"provider": "gemini", "duration_ms": 4000},
    ))
    library.create(_playlist(
        name="Focus Flow",
        artists=["Tame Impala"],
        tags={"genre": ["Synthwave", "Ambient"], "mood": [], "period": []},
        generation_meta={"provider": "openai", "duration_ms": 2000},
        youtube=True,
    ))
    library.create(_playlist(
        name="Untagged",
        artists=["Some Artist"],
        # No tags, no generation_meta -- simulates a playlist saved before this
        # feature existed.
    ))
    return library


def test_compute_stats_aggregates_across_the_library(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "playlists.db"
    _seed_library(database_path)
    monkeypatch.setattr(playlist_stats, "DATABASE_PATH", database_path)

    counter_path = tmp_path / "generation_counter.json"
    monkeypatch.setattr(generation_counter, "GENERATION_COUNTER_PATH", counter_path)
    generation_counter.record_generation()
    generation_counter.record_generation()
    generation_counter.record_generation()
    generation_counter.record_generation()  # one more "generated" than "saved"

    errors_path = tmp_path / "generation_errors.json"
    monkeypatch.setattr(generation_errors, "GENERATION_ERRORS_PATH", errors_path)
    generation_errors.record_generation_error(ValueError("insufficient tracks"))

    stats = playlist_stats.compute_stats()

    general = stats["general"]
    assert general["total_generated"] == 4
    assert general["total_saved"] == 3
    assert general["total_published"] == 1
    assert general["top_genres"][0] == {"label": "Synthwave", "count": 2}
    assert {"label": "Tame Impala", "count": 2} in general["top_artists"]
    # Music-taste data (genre/artist/mood/period) all lives in `general`, not `nerd`.
    assert {"label": "Dreamy", "count": 1} in general["top_moods"]
    assert {"label": "1980s", "count": 1} in general["top_periods"]
    # The "playlists over time" chart tracks every generation (not just saved
    # playlists), so it sums to total_generated rather than total_saved.
    current_month = datetime.now(UTC).strftime("%Y-%m")
    assert general["playlists_by_month"] == {current_month: 4}
    assert sum(general["playlists_by_month"].values()) == general["total_generated"]

    nerd = stats["nerd"]
    assert nerd["provider_breakdown"] == {"gemini": 1, "openai": 1, "unknown": 1}
    assert nerd["duration_sample_size"] == 2
    assert nerd["avg_generation_ms"] == 3000
    assert nerd["median_generation_ms"] == 3000
    assert nerd["tag_coverage_percent"] == round(100 * 2 / 3, 1)
    assert nerd["draft_vs_published"] == {"draft": 2, "published": 1}
    assert nerd["error_breakdown"] == {"ValueError": 1}
    assert nerd["total_errors"] == 1
    assert "top_moods" not in nerd
    assert "top_periods" not in nerd


def test_compute_stats_handles_an_empty_library(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(playlist_stats, "DATABASE_PATH", tmp_path / "missing.db")
    monkeypatch.setattr(
        generation_counter, "GENERATION_COUNTER_PATH", tmp_path / "generation_counter.json"
    )
    monkeypatch.setattr(
        generation_errors, "GENERATION_ERRORS_PATH", tmp_path / "generation_errors.json"
    )

    stats = playlist_stats.compute_stats()

    assert stats["general"]["total_generated"] == 0
    assert stats["general"]["total_saved"] == 0
    assert stats["general"]["top_genres"] == []
    assert stats["general"]["top_moods"] == []
    assert stats["general"]["playlists_by_month"] == {}
    assert stats["nerd"]["avg_generation_ms"] is None
    assert stats["nerd"]["tag_coverage_percent"] is None
    assert stats["nerd"]["error_breakdown"] == {}
    assert stats["nerd"]["total_errors"] == 0
