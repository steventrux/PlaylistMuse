from __future__ import annotations

import asyncio

from backend import reccobeats_runtime
from backend.generation_runtime import _reccobeats_replenishment_guidance
from backend.popularity_intent import PopularityIntent, intent_from_payload
from backend.reccobeats_anchors import anchors_from_payload
from backend.reccobeats_popularity import (
    canonicalize_reccobeats_matches,
    enrich_recommendation_popularity,
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


def test_popularity_guidance_uses_ranked_pool_without_becoming_hard_constraint() -> None:
    candidates = [
        _candidate("Artist A", "Hit", 90),
        _candidate("Artist B", "Deep Cut", 12),
    ]

    popular = _reccobeats_replenishment_guidance(candidates, "popular")
    less_known = _reccobeats_replenishment_guidance(candidates, "less_known")

    assert "broader ReccoBeats pool" in popular
    assert "higher known popularity values" in popular
    assert "lower known popularity values" in less_known
    assert "primary source of song identities" in popular
    assert "primary source of song identities" in less_known
    assert "soft preference" in popular
    assert "never overrides eligibility or creative fit" in popular
    assert "missing popularity value is neutral" in less_known
    assert "more familiar unlisted song" in less_known


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


def test_neutral_recco_fallback_uses_secondary_anchors_when_primary_returns_nothing(
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
        assert preference == "neutral"
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
        reccobeats_runtime._recommend_with_fallback(anchors, 25, "neutral")
    )

    assert result == [fallback_candidate]
    assert metadata["primary_candidates"] == 0
    assert metadata["fallback_used"] is True
    assert metadata["fallback_candidates"] == 1
    assert metadata["fallback_result_counts"] == (0, 0, 0, 1)
    assert metadata["expanded_pool"] is False


def test_neutral_primary_success_keeps_single_recommendation_call(monkeypatch) -> None:
    anchors = [
        {"artist": f"Artist {letter}", "title": f"Song {letter}"}
        for letter in "ABCDEF"
    ]
    primary_candidate = _candidate("Primary Artist", "Primary Song", 88)
    calls = []

    async def fake_recommend(tracks, *, limit, max_anchors):
        calls.append([track["artist"] for track in tracks])
        assert limit == 24
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
        reccobeats_runtime._recommend_with_fallback(anchors, 25, "neutral")
    )

    assert result == [primary_candidate]
    assert calls == [["Artist A", "Artist B", "Artist C"]]
    assert metadata["fallback_used"] is False
    assert metadata["expanded_pool"] is False


def test_explicit_popularity_builds_large_pool_then_keeps_requested_extreme(
    monkeypatch,
) -> None:
    anchors = [
        {"artist": f"Artist {letter}", "title": f"Song {letter}"}
        for letter in "ABCDEF"
    ]
    calls: list[list[str]] = []
    counter = 0

    async def fake_recommend(tracks, *, limit, max_anchors):
        nonlocal counter
        assert limit == 30
        assert max_anchors == 3
        calls.append([track["artist"] for track in tracks])
        batch: list[dict] = []
        for _ in range(20):
            counter += 1
            batch.append(_candidate(f"Candidate {counter}", f"Song {counter}", counter))
        return batch

    async def fake_enrich(candidates, *, preference):
        reverse = preference == "popular"
        return sorted(candidates, key=lambda item: item["popularity"], reverse=reverse)

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

    popular, metadata = asyncio.run(
        reccobeats_runtime._recommend_with_fallback(anchors, 25, "popular")
    )

    assert len(calls) == 4
    assert all(1 <= len(call) <= 3 for call in calls)
    assert len(popular) == 24
    assert [item["popularity"] for item in popular] == list(range(72, 48, -1))
    assert metadata["expanded_pool"] is True
    assert metadata["discovery_batches"] == 4
    assert metadata["pool_candidates"] == 72
    assert metadata["context_candidates"] == 24
    assert metadata["pool_popularity_min"] == 1
    assert metadata["pool_popularity_max"] == 72


def test_explicit_less_known_keeps_low_end_of_aggregate_pool(monkeypatch) -> None:
    anchors = [
        {"artist": f"Artist {letter}", "title": f"Song {letter}"}
        for letter in "ABCDEF"
    ]
    counter = 0

    async def fake_recommend(tracks, *, limit, max_anchors):
        nonlocal counter
        batch: list[dict] = []
        for _ in range(18):
            counter += 1
            batch.append(_candidate(f"Candidate {counter}", f"Song {counter}", counter))
        return batch

    async def fake_enrich(candidates, *, preference):
        return sorted(candidates, key=lambda item: item["popularity"])

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

    less_known, metadata = asyncio.run(
        reccobeats_runtime._recommend_with_fallback(anchors, 25, "less_known")
    )

    assert [item["popularity"] for item in less_known] == list(range(1, 25))
    assert metadata["pool_candidates"] == 72
    assert metadata["context_popularity_min"] == 1
    assert metadata["context_popularity_max"] == 24


def test_large_popularity_enrichment_is_split_into_bounded_detail_batches(
    monkeypatch,
) -> None:
    calls: list[list[str]] = []

    class FakeResponse:
        def __init__(self, ids: list[str]) -> None:
            self.ids = ids

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "content": [
                    {"id": value, "popularity": index}
                    for index, value in enumerate(self.ids, start=1)
                ]
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params):
            ids = str(params["ids"]).split(",")
            calls.append(ids)
            return FakeResponse(ids)

    monkeypatch.setattr(
        "backend.reccobeats_popularity.httpx.AsyncClient",
        lambda *args, **kwargs: FakeClient(),
    )

    candidates = [
        {
            "artist": f"Artist {index}",
            "title": f"Song {index}",
            "reccobeats_id": f"id-{index}",
        }
        for index in range(65)
    ]
    result = asyncio.run(
        enrich_recommendation_popularity(candidates, preference="popular")
    )

    assert sorted(len(batch) for batch in calls) == [5, 30, 30]
    assert len(result) == 65
    assert all("popularity" in item for item in result)


def test_popularity_summary_reports_only_known_values() -> None:
    assert reccobeats_runtime._popularity_summary(
        [
            _candidate("A", "One", 10),
            _candidate("B", "Two"),
            _candidate("C", "Three", 70),
        ]
    ) == (2, 10, 70, 40.0)
