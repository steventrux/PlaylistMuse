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
        generation_meta={
            "provider": "gemini",
            "duration_ms": 4000,
            "stage_timings_ms": {"ai_draft": 1000, "youtube_resolution": 3000},
            "complexity_score": 40,
        },
    ))
    library.create(_playlist(
        name="Focus Flow",
        artists=["Tame Impala"],
        tags={"genre": ["Synthwave", "Ambient"], "mood": [], "period": []},
        generation_meta={
            "provider": "openai",
            "duration_ms": 2000,
            "stage_timings_ms": {"ai_draft": 600, "youtube_resolution": 1400},
        },
        youtube=True,
    ))
    library.create(_playlist(
        name="Untagged",
        artists=["Some Artist"],
        # No tags, no generation_meta -- simulates a playlist saved before this
        # feature existed.
    ))
    return library


def test_top_artists_keeps_a_comma_in_a_band_name_intact(monkeypatch, tmp_path: Path) -> None:
    """Regression test: "Earth, Wind & Fire" must not be split into "Earth" and
    "Wind & Fire" the way a genuine two-artist credit like "Daft Punk, Julian
    Casablancas" should be."""
    database_path = tmp_path / "playlists.db"
    library = PlaylistLibrary(database_path)
    library.create(_playlist(name="Groove", artists=["Earth, Wind & Fire"]))
    library.create(_playlist(name="Collab", artists=["Daft Punk, Julian Casablancas"]))
    monkeypatch.setattr(playlist_stats, "DATABASE_PATH", database_path)

    stats = playlist_stats.compute_stats()

    top_artists = stats["general"]["top_artists"]
    assert {"label": "Earth, Wind & Fire", "count": 1} in top_artists
    assert {"label": "Earth", "count": 1} not in top_artists
    assert {"label": "Wind & Fire", "count": 1} not in top_artists
    assert {"label": "Daft Punk", "count": 1} in top_artists
    assert {"label": "Julian Casablancas", "count": 1} in top_artists


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
    generation_errors.record_generation_error(
        ValueError("insufficient tracks"), provider="gemini"
    )

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

    by_provider = stats["nerd"]["by_provider"]
    assert set(by_provider) == {"gemini", "openai", "unknown"}

    gemini = by_provider["gemini"]
    assert gemini["playlist_count"] == 1
    assert gemini["duration_sample_size"] == 1
    assert gemini["avg_generation_ms"] == 4000
    assert gemini["median_generation_ms"] == 4000
    assert gemini["avg_complexity_score"] == 40
    assert gemini["tag_coverage_percent"] == 100.0
    assert gemini["draft_vs_published"] == {"draft": 1, "published": 0}
    assert gemini["error_breakdown"] == {"ValueError": 1}
    assert gemini["total_errors"] == 1
    assert gemini["stage_timings"]["ai_draft"] == {
        "avg_ms": 1000,
        "median_ms": 1000,
        "p95_ms": 1000,
        "sample_size": 1,
    }

    openai = by_provider["openai"]
    assert openai["playlist_count"] == 1
    assert openai["avg_generation_ms"] == 2000
    # No complexity_score recorded for this playlist (e.g. seed-mode generation) --
    # excluded from the average rather than counted as 0.
    assert openai["avg_complexity_score"] is None
    assert openai["draft_vs_published"] == {"draft": 0, "published": 1}
    assert openai["error_breakdown"] == {}
    assert openai["total_errors"] == 0

    unknown = by_provider["unknown"]
    assert unknown["playlist_count"] == 1
    assert unknown["avg_generation_ms"] is None
    assert unknown["tag_coverage_percent"] == 0.0
    assert unknown["draft_vs_published"] == {"draft": 1, "published": 0}


def test_compute_stats_normalizes_genre_and_mood_casing(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "playlists.db"
    library = PlaylistLibrary(database_path)
    library.create(_playlist(
        name="Morning Run",
        artists=["Artist A"],
        tags={"genre": ["synthwave"], "mood": ["energetic"], "period": []},
    ))
    library.create(_playlist(
        name="Evening Run",
        artists=["Artist B"],
        tags={"genre": ["Synthwave"], "mood": ["Energetic"], "period": []},
    ))
    library.create(_playlist(
        name="Night Run",
        artists=["Artist C"],
        tags={"genre": ["SYNTHWAVE"], "mood": ["ENERGETIC"], "period": []},
    ))
    monkeypatch.setattr(playlist_stats, "DATABASE_PATH", database_path)

    stats = playlist_stats.compute_stats()

    assert stats["general"]["top_genres"] == [{"label": "Synthwave", "count": 3}]
    assert stats["general"]["top_moods"] == [{"label": "Energetic", "count": 3}]


def test_compute_stats_aggregates_and_normalizes_custom_tags(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "playlists.db"
    library = PlaylistLibrary(database_path)
    library.create(_playlist(
        name="Morning Run",
        artists=["Artist A"],
        tags={"genre": [], "mood": [], "period": [], "custom": ["road trip"]},
    ))
    library.create(_playlist(
        name="Evening Run",
        artists=["Artist B"],
        tags={"genre": [], "mood": [], "period": [], "custom": ["Road Trip", "favorites"]},
    ))
    monkeypatch.setattr(playlist_stats, "DATABASE_PATH", database_path)

    stats = playlist_stats.compute_stats()

    custom_tags = {
        entry["label"]: entry["count"] for entry in stats["general"]["top_custom_tags"]
    }
    assert custom_tags == {"Road Trip": 2, "Favorites": 1}
    # Personal tags are freeform organization, not AI classification -- they must
    # not count toward a provider's tag_coverage_percent.
    unknown = stats["nerd"]["by_provider"]["unknown"]
    assert unknown["tag_coverage_percent"] == 0.0


def test_compute_stats_splits_combined_period_ranges(monkeypatch, tmp_path: Path) -> None:
    database_path = tmp_path / "playlists.db"
    library = PlaylistLibrary(database_path)
    library.create(_playlist(
        name="Retro Mix",
        artists=["Artist A"],
        tags={"genre": [], "mood": [], "period": ["1970s-1980s"]},
    ))
    library.create(_playlist(
        name="Eighties Only",
        artists=["Artist B"],
        tags={"genre": [], "mood": [], "period": ["1980s"]},
    ))
    monkeypatch.setattr(playlist_stats, "DATABASE_PATH", database_path)

    stats = playlist_stats.compute_stats()

    periods = {entry["label"]: entry["count"] for entry in stats["general"]["top_periods"]}
    assert periods == {"1970s": 1, "1980s": 2}


def test_expand_period_only_splits_genuine_decade_ranges() -> None:
    assert playlist_stats._expand_period("1970s-1980s") == ["1970s", "1980s"]
    assert playlist_stats._expand_period("1980s") == ["1980s"]
    # A hyphenated value that isn't a decade-to-decade range is left untouched
    # rather than being split apart.
    assert playlist_stats._expand_period("Post-2000") == ["Post-2000"]


def test_stage_timings_filter_out_retired_stage_names(monkeypatch, tmp_path: Path) -> None:
    """Regression: a playlist generated before a feature's removal (e.g. the
    retired Track Journey mode) can still carry that feature's stage name baked
    into its persisted generation_meta. The playlist data itself is never
    touched, but a stage nothing can produce anymore must not keep surfacing in
    the aggregate "AI performance" stats.
    """
    database_path = tmp_path / "playlists.db"
    monkeypatch.setattr(playlist_stats, "DATABASE_PATH", database_path)
    monkeypatch.setattr(
        generation_counter, "GENERATION_COUNTER_PATH", tmp_path / "generation_counter.json"
    )
    monkeypatch.setattr(
        generation_errors, "GENERATION_ERRORS_PATH", tmp_path / "generation_errors.json"
    )

    library = PlaylistLibrary(database_path)
    library.create(_playlist(
        name="Old Journey Mix",
        artists=["Some Artist"],
        generation_meta={
            "provider": "gemini",
            "duration_ms": 5000,
            "stage_timings_ms": {
                "llm_initial": 2000,
                "journey_ordering": 3000,
            },
        },
    ))

    stats = playlist_stats.compute_stats()

    stage_timings = stats["nerd"]["by_provider"]["gemini"]["stage_timings"]
    assert "llm_initial" in stage_timings
    assert "journey_ordering" not in stage_timings


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
    assert stats["general"]["top_custom_tags"] == []
    assert stats["general"]["playlists_by_month"] == {}
    assert stats["nerd"]["by_provider"] == {}
