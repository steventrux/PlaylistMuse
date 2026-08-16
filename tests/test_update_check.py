from __future__ import annotations

import asyncio

import httpx
from fastapi.testclient import TestClient

import backend.build_info as build_info
from backend.application import app
from backend.update_check import _clear_cache, check_for_update


def test_stable_channel_reports_update_when_a_newer_release_exists() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/steventrux/PlaylistMuse/releases/latest"
        return httpx.Response(
            200,
            json={
                "tag_name": "v0.3.0",
                "html_url": "https://github.com/steventrux/PlaylistMuse/releases/tag/v0.3.0",
            },
        )

    async def run() -> dict:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await check_for_update(
                channel="stable",
                version="0.2.2",
                commit_sha="",
                client=client,
                now=lambda: 100.0,
            )

    _clear_cache()
    result = asyncio.run(run())
    assert result == {
        "update_available": True,
        "latest": "0.3.0",
        "url": "https://github.com/steventrux/PlaylistMuse/releases/tag/v0.3.0",
    }


def test_stable_channel_reports_no_update_when_already_current() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "tag_name": "v0.2.2",
                "html_url": "https://github.com/steventrux/PlaylistMuse/releases/tag/v0.2.2",
            },
        )

    async def run() -> dict:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await check_for_update(
                channel="stable",
                version="0.2.2",
                commit_sha="",
                client=client,
                now=lambda: 100.0,
            )

    _clear_cache()
    result = asyncio.run(run())
    assert result["update_available"] is False
    assert result["latest"] == "0.2.2"


def test_dev_channel_compares_full_commit_sha() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/steventrux/PlaylistMuse/commits/dev"
        return httpx.Response(
            200,
            json={
                "sha": "a" * 40,
                "html_url": "https://github.com/steventrux/PlaylistMuse/commit/" + "a" * 40,
            },
        )

    async def run(local_sha: str) -> dict:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await check_for_update(
                channel="dev",
                version="dev",
                commit_sha=local_sha,
                client=client,
                now=lambda: 100.0,
            )

    _clear_cache()
    stale = asyncio.run(run("b" * 40))
    assert stale["update_available"] is True
    assert stale["latest"] == "a" * 7

    _clear_cache()
    current = asyncio.run(run("a" * 40))
    assert current["update_available"] is False


def test_beta_channel_is_unknown_without_any_http_call() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    async def run() -> dict:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await check_for_update(
                channel="beta",
                version="0.3.0-beta.1",
                commit_sha="",
                client=client,
                now=lambda: 100.0,
            )

    _clear_cache()
    result = asyncio.run(run())
    assert result == {"update_available": None, "latest": None, "url": None}
    assert calls == 0


def test_failure_degrades_gracefully_and_the_outcome_is_cached() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"message": "rate limited"})

    async def run() -> tuple[dict, dict]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            first = await check_for_update(
                channel="stable",
                version="0.2.2",
                commit_sha="",
                client=client,
                now=lambda: 100.0,
            )
            second = await check_for_update(
                channel="stable",
                version="0.2.2",
                commit_sha="",
                client=client,
                now=lambda: 101.0,
            )
        return first, second

    _clear_cache()
    first, second = asyncio.run(run())
    assert first == {"update_available": None, "latest": None, "url": None}
    assert second == first
    assert calls == 1


def test_version_update_endpoint_wires_build_info_through(monkeypatch) -> None:
    async def fake_check_for_update(*, channel, version, commit_sha, **_):
        assert channel == "stable"
        assert version == build_info.APP_VERSION
        return {"update_available": True, "latest": "9.9.9", "url": "https://example.invalid"}

    monkeypatch.setattr(build_info, "check_for_update", fake_check_for_update)
    monkeypatch.setenv("PLAYLISTMUSE_CHANNEL", "stable")
    monkeypatch.delenv("PLAYLISTMUSE_VERSION", raising=False)

    response = TestClient(app).get("/api/version/update")

    assert response.status_code == 200
    assert response.json() == {
        "update_available": True,
        "latest": "9.9.9",
        "url": "https://example.invalid",
    }
