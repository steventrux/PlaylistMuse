from __future__ import annotations

import asyncio

from backend import generation_runtime
from backend.popularity_intent import (
    PopularityIntent,
    activate_popularity_intent,
    reset_popularity_intent,
)
from backend.reccobeats_runtime import _generation_count, _score_and_rank_tracks


def _track(artist: str, title: str, popularity=None) -> dict:
    result = {
        "artist": artist,
        "title": title,
        "description": f"Description {title}",
        "reason": f"Reason {title}",
    }
    if popularity is not None:
        result["popularity"] = popularity
    return result


def test_popularity_candidate_buffer_is_bounded_and_only_explicit() -> None:
    assert _generation_count(25, PopularityIntent("popular", 1.0), "llm_initial") == 30
    assert _generation_count(10, PopularityIntent("less_known", 1.0), "llm_initial") == 14
    assert _generation_count(25, PopularityIntent("neutral", 1.0), "llm_initial") == 25
    assert _generation_count(25, PopularityIntent("popular", 1.0), "llm_replenishment") == 25


def test_llm_tracks_are_ranked_by_recco_popularity_without_absolute_thresholds(monkeypatch) -> None:
    tracks = [
        _track("Artist A", "Medium"),
        _track("Artist B", "High"),
        _track("Artist C", "Low"),
    ]

    async def fake_scores(items):
        return {
            ("artist a", "medium"): 50,
            ("artist b", "high"): 90,
            ("artist c", "low"): 10,
        }

    monkeypatch.setattr("backend.reccobeats_runtime.popularity_for_tracks", fake_scores)

    popular = asyncio.run(
        _score_and_rank_tracks(tracks, PopularityIntent("popular", 1.0))
    )
    less_known = asyncio.run(
        _score_and_rank_tracks(tracks, PopularityIntent("less_known", 1.0))
    )

    assert [item["title"] for item in popular] == ["High", "Medium", "Low"]
    assert [item["title"] for item in less_known] == ["Low", "Medium", "High"]
    assert [item["popularity"] for item in popular] == [90, 50, 10]


def test_catalogue_selection_rank_reverses_for_popular_and_less_known() -> None:
    high = {"artists": "A", "title": "High", "album": "A1", "popularity": 90}
    low = {"artists": "B", "title": "Low", "album": "B1", "popularity": 10}

    token = activate_popularity_intent(PopularityIntent("popular", 1.0))
    try:
        assert generation_runtime._diversity_rank(high, []) < generation_runtime._diversity_rank(low, [])
    finally:
        reset_popularity_intent(token)

    token = activate_popularity_intent(PopularityIntent("less_known", 1.0))
    try:
        assert generation_runtime._diversity_rank(low, []) < generation_runtime._diversity_rank(high, [])
    finally:
        reset_popularity_intent(token)
