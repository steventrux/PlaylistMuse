from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

import backend.main as main_module
import backend.telemetry as telemetry


def test_telemetry_is_disabled_by_default_and_toggle_persists(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "telemetry.json"
    monkeypatch.setattr(telemetry, "TELEMETRY_PATH", path)

    assert telemetry.telemetry_enabled() is False
    assert telemetry.telemetry_settings_response() == {"enabled": False}

    assert telemetry.set_telemetry_enabled(True) == {"enabled": True}
    assert telemetry.telemetry_enabled() is True

    assert telemetry.set_telemetry_enabled(False) == {"enabled": False}
    assert telemetry.telemetry_enabled() is False


def test_report_playlist_generated_is_a_no_op_without_an_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(telemetry, "TELEMETRY_ENDPOINT", "")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request should be made when no endpoint is configured")

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            await telemetry.report_playlist_generated(client=client)

    asyncio.run(run())


def test_report_playlist_generated_sends_no_identifying_data(monkeypatch) -> None:
    monkeypatch.setattr(telemetry, "TELEMETRY_ENDPOINT", "https://stats.example.test/ping")
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = request.content
        seen["params"] = dict(request.url.params)
        return httpx.Response(204)

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            await telemetry.report_playlist_generated(client=client)

    asyncio.run(run())

    assert seen["method"] == "POST"
    assert seen["url"] == "https://stats.example.test/ping"
    assert seen["body"] == b""
    assert seen["params"] == {}


def test_telemetry_settings_routes_control_the_opt_in_flag(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(telemetry, "TELEMETRY_PATH", tmp_path / "telemetry.json")
    client = TestClient(main_module.app)

    initial = client.get("/api/telemetry/settings")
    assert initial.status_code == 200
    assert initial.json() == {"enabled": False}

    enabled = client.put("/api/telemetry/settings", json={"enabled": True})
    assert enabled.status_code == 200
    assert enabled.json() == {"enabled": True}
    assert client.get("/api/telemetry/settings").json() == {"enabled": True}

    disabled = client.put("/api/telemetry/settings", json={"enabled": False})
    assert disabled.json() == {"enabled": False}


def test_report_playlist_generated_swallows_failures(monkeypatch) -> None:
    monkeypatch.setattr(telemetry, "TELEMETRY_ENDPOINT", "https://stats.example.test/ping")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            # Must not raise even though the server errors.
            await telemetry.report_playlist_generated(client=client)

    asyncio.run(run())
