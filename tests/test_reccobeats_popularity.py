from __future__ import annotations

import asyncio

from backend import reccobeats_runtime
from backend.generation_runtime import _reccobeats_replenishment_guidance
from backend.popularity_intent import PopularityIntent, intent_from_payload
from backend.reccobeats_anchors import anchors_from_payload
from backend.reccobeats_popularity import (
    canonicalize_reccobeats_matches,
    rank_by_popularity,
)


def _candidate(artist: str, title: str, popularity=None):
    result = {
        "artist": artist,
        "title": title,
        "source": "reccobeats",
        "reccobeats_id": f"{artist}-{title}",
    }
    if popularity is not None:
        result["popularity"] = popularity
    return result


def test_popularity_intent_requires_confident_explicit_preference() -> None:
    popular = intent_from_payload({"preference": "popular", "confidence": 0.95})
    obscure = intent_from_payload({"preference": "less_known", "confidence": 0.90})
    uncertain = intent_from_payload({"preference": "popular", "confidence": 0.50})
    neutral = intent_from_payload({"preference": "neutral", "confidence": 0.99})

    assert popular == PopularityIntent("popular", 0.95)
    assert popular.active
    assert obscure.active
    assert not uncertain.active
    assert not neutral.active


def test_recco_popularity_ranking_is_relative_and_missing_is_neutral() -> None:
    candidates = [
        _candidate("A", "Medium", 40),
        _candidate("B", "Unknown"),
        _candidate("C", "Popular", 90),
        _candidate("D", "Deep", 10),
    ]

    popular = rank_by_popularity(candidates, "popular")
    less_known = rank_by_popularity(candidates, "less_known")
    neutral = rank_by_popularity(candidates, "neutral")

    assert [item["title"] for item in popular] == ["Popular", "Medium", "Deep", "Unknown"]
    assert [item["title"] for item in less_known] == ["Deep", "Medium", "Popular", "Unknown"]
    assert [item["title"] for item in neutral] == ["Medium", "Unknown", "Popular", "Deep"]


def test_popularity_guidance_never_turns_score_into_hard_constraint() -> None:
    candidates = [
        _candidate("Artist A", "Hit", 90),
        _candidate("Artist B", "Deep Cut", 12),
    ]

    popular = _reccobeats_replenishment_guidance(candidates, "popular")
    less_known = _reccobeats_replenishment_guidance(candidates, "less_known")

    assert "higher Recco popularity values" in popular
    assert "lower known Recco popularity values" in less_known
    assert "soft preference" in popular
    assert "never overrides eligibility or creative fit" in popular
    assert "missing popularity value is neutral" in less_known


def test_canonical_recco_identity_keeps_llm_explanations() -> None:
    candidates = [
        {
            "artist": "Canonical Artist",
            "title": "Canonical Song",
            "source": "reccobeats",
            "reccobeats_id": "track-1",
            "popularity": 77,
        }
    ]
    tracks = [
        {
            "artist": " canonical artist ",
            "title": "CANONICAL SONG",
            "description": "LLM description",
            "reason": "LLM reason",
        },
        {
            "artist": "Other Artist",
            "title": "Other Song",
            "description": "Other description",
            "reason": "Other reason",
        },
    ]

    result = canonicalize_reccobeats_matches(tracks, candidates)

    assert result[0] == {
        "artist": "Canonical Artist",
        "title": "Canonical Song",
        "description": "LLM description",
        "reason": "LLM reason",
        "source": "reccobeats",
        "reccobeats_id": "track-1",
        "popularity": 77,
    }
    assert result[1] == tracks[1]


def test_anchor_payload_deduplicates_identity_and_caps_at_six() -> None:
    anchors = anchors_from_payload(
        {
            "anchors": [
                {"artist": "Artist A", "title": "Song One"},
                {"artist": " artist a ", "title": "SONG ONE"},
                {"artist": "Artist B", "title": "Song Two"},
                {"artist": "Artist C", "title": "Song Three"},
                {"artist": "Artist D", "title": "Song Four"},
                {"artist": "Artist E", "title": "Song Five"},
                {"artist": "Artist F", "title": "Song Six"},
                {"artist": "Artist G", "title": "Song Seven"},
            ]
        }
    )

    assert [(item.artist, item.title) for item in anchors] == [
        ("Artist A", "Song One"),
        ("Artist B", "Song Two"),
        ("Artist C", "Song Three"),
        ("Artist D", "Song Four"),
        ("Artist E", "Song Five"),
        ("Artist F", "Song Six"),
    ]


def test_recco_fallback_uses_secondary_anchors_when_primary_returns_nothing(
    monkeypatch,
) -> None:
    anchors = [
        {"artist": f"Artist {letter}", "title": f"Song {letter}"}
        for letter in "ABCDEF"
    ]
    fallback_candidate = _candidate("Fallback Artist", "Fallback Song", 32)

    async def fake_recommend(tracks, *, limit, max_anchors):
        assert limit == 24
        assert max_anchors == 3
        if tracks and tracks[0]["artist"] == "Artist D":
            return [fallback_candidate]
        return []

    async def fake_enrich(candidates, *, preference):
        assert preference == "less_known"
        return list(candidates)

    monkeypatch.setattr(
        reccobeats_runtime,
        "recommendation_candidates_from_tracks",
        fake_recommend,
    )
    monkeypatch.setattr(
        reccobeats_runtime,
        "enrich_recommendation_popularity",
        fake_enrich,
    )

    result, metadata = asyncio.run(
        reccobeats_runtime._recommend_with_fallback(anchors, 25, "less_known")
    )

    assert result == [fallback_candidate]
    assert metadata["primary_candidates"] == 0
    assert metadata["fallback_used"] is True
    assert metadata["fallback_candidates"] == 1
    assert metadata["fallback_result_counts"] == (0, 0, 0, 1)


def test_recco_primary_success_does_not_trigger_fallback(monkeypatch) -> None:
    anchors = [
        {"artist": f"Artist {letter}", "title": f"Song {letter}"}
        for letter in "ABCDEF"
    ]
    primary_candidate = _candidate("Primary Artist", "Primary Song", 88)
    calls = []

    async def fake_recommend(tracks, *, limit, max_anchors):
        calls.append([track["artist"] for track in tracks])
        return [primary_candidate]

    async def fake_enrich(candidates, *, preference):
        return list(candidates)

    monkeypatch.setattr(
        reccobeats_runtime,
        "recommendation_candidates_from_tracks",
        fake_recommend,
    )
    monkeypatch.setattr(
        reccobeats_runtime,
        "enrich_recommendation_popularity",
        fake_enrich,
    )

    result, metadata = asyncio.run(
        reccobeats_runtime._recommend_with_fallback(anchors, 25, "popular")
    )

    assert result == [primary_candidate]
    assert calls == [["Artist A", "Artist B", "Artist C"]]
    assert metadata["fallback_used"] is False


def test_popularity_summary_reports_only_known_values() -> None:
    assert reccobeats_runtime._popularity_summary(
        [
            _candidate("A", "One", 10),
            _candidate("B", "Two"),
            _candidate("C", "Three", 70),
        ]
    ) == (2, 10, 70, 40.0)
