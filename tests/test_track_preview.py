from __future__ import annotations

import asyncio

import httpx
from fastapi.testclient import TestClient

from backend.application import app
from backend.track_preview import _clear_cache, find_preview_url


def test_track_preview_returns_url_and_caches_result() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert 'artist:"AC/DC"' in request.url.params["q"]
        assert 'track:"Back in Black"' in request.url.params["q"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "title": "Back in Black",
                        "artist": {"name": "AC/DC"},
                        "preview": "https://cdn.deezer.example/preview.mp3",
                    }
                ]
            },
        )

    async def run() -> tuple[str | None, str | None]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            first = await find_preview_url(
                "Back in Black", "AC/DC", client=client, now=lambda: 100.0
            )
            second = await find_preview_url(
                "Back in Black", "AC/DC", client=client, now=lambda: 101.0
            )
        return first, second

    _clear_cache()
    first, second = asyncio.run(run())
    assert first == "https://cdn.deezer.example/preview.mp3"
    assert second == first
    assert calls == 1


def test_track_preview_returns_none_without_match() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    async def run() -> str | None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await find_preview_url(
                "Unknown Track", "Unknown Artist", client=client, now=lambda: 0.0
            )

    _clear_cache()
    assert asyncio.run(run()) is None


def test_track_preview_failure_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async def run() -> str | None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await find_preview_url(
                "Back in Black", "AC/DC", client=client, now=lambda: 0.0
            )

    _clear_cache()
    assert asyncio.run(run()) is None


def test_track_preview_missing_input_returns_none_without_request() -> None:
    _clear_cache()
    assert asyncio.run(find_preview_url("", "AC/DC")) is None
    assert asyncio.run(find_preview_url("Back in Black", "")) is None


def test_track_preview_endpoint_returns_preview_url(monkeypatch) -> None:
    async def fake_find_preview_url(title: str, artist: str) -> str | None:
        assert title == "Back in Black"
        assert artist == "AC/DC"
        return "https://cdn.deezer.example/preview.mp3"

    monkeypatch.setattr(
        "backend.track_preview.find_preview_url", fake_find_preview_url
    )

    client = TestClient(app)
    response = client.get("/api/tracks/preview", params={"title": "Back in Black", "artist": "AC/DC"})
    assert response.status_code == 200
    assert response.json() == {"preview_url": "https://cdn.deezer.example/preview.mp3"}
