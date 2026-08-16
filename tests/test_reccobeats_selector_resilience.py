from __future__ import annotations

import asyncio
import json

from backend.config import AppConfig
from backend import reccobeats_popularity, reccobeats_selector


def _config() -> AppConfig:
    return AppConfig(
        provider="custom",
        model="primary",
        base_url="http://provider.test",
    )


def _candidate(index: int, popularity: int = 70) -> dict:
    return {
        "artist": f"Artist {index}",
        "title": f"Song {index}",
        "source": "reccobeats",
        "reccobeats_id": f"id-{index}",
        "popularity": popularity,
    }


def test_selector_falls_back_to_smaller_batches_and_preserves_identities(monkeypatch) -> None:
    calls = 0

    async def fake_request(config, prompt, *, system_prompt, max_tokens, model=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("full selector failed")
        candidate_count = prompt.count("[popularity=")
        selections = [
            {"index": index, "description": f"Description {index}", "reason": f"Reason {index}"}
            for index in range(1, candidate_count + 1)
        ]
        return json.dumps({"title": "Test", "description": "Test", "selections": selections})

    monkeypatch.setattr(reccobeats_selector, "request_structured_json", fake_request)
    candidates = [_candidate(index) for index in range(1, 26)]

    draft = asyncio.run(
        reccobeats_selector.select_reccobeats_draft(
            _config(),
            "party tracks",
            candidates,
            count=25,
            preference="popular",
        )
    )

    assert draft is not None
    assert calls == 4
    assert len(draft["tracks"]) == 25
    assert [track["reccobeats_id"] for track in draft["tracks"]] == [
        f"id-{index}" for index in range(1, 26)
    ]
    assert all(track["source"] == "reccobeats" for track in draft["tracks"])


def test_selector_uses_deterministic_locked_pool_when_provider_is_unavailable(monkeypatch) -> None:
    async def unavailable(*args, **kwargs):
        raise RuntimeError("selector unavailable")

    monkeypatch.setattr(reccobeats_selector, "request_structured_json", unavailable)
    candidates = [_candidate(index, 20) for index in range(1, 7)]

    draft = asyncio.run(
        reccobeats_selector.select_reccobeats_draft(
            _config(),
            "less known party tracks",
            candidates,
            count=5,
            preference="less_known",
        )
    )

    assert draft is not None
    assert [track["reccobeats_id"] for track in draft["tracks"]] == [
        "id-1",
        "id-2",
        "id-3",
        "id-4",
        "id-5",
    ]
    assert all(track["description"] for track in draft["tracks"])
    assert all(track["reason"] for track in draft["tracks"])


def test_request_scoped_popularity_cache_preserves_known_score_after_later_failure(monkeypatch) -> None:
    calls = 0

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"content": [{"id": "id-1", "popularity": 77}]}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, params):
            nonlocal calls
            calls += 1
            if calls > 1:
                raise RuntimeError("network should not be used for cached id")
            return FakeResponse()

    monkeypatch.setattr(
        reccobeats_popularity.httpx,
        "AsyncClient",
        lambda *args, **kwargs: FakeClient(),
    )
    candidate = _candidate(1)
    candidate.pop("popularity")

    async def run_request():
        reccobeats_popularity.reset_request_popularity_cache()
        first = await reccobeats_popularity.enrich_recommendation_popularity(
            [candidate], preference="popular"
        )
        second = await reccobeats_popularity.enrich_recommendation_popularity(
            [candidate], preference="popular"
        )
        return first, second

    first, second = asyncio.run(run_request())

    assert first[0]["popularity"] == 77
    assert second[0]["popularity"] == 77
    assert calls == 1
