from __future__ import annotations

import asyncio

import backend.main as main_module
from backend.generation_stage_timing import record_stage_ms


class _FakeConfig:
    provider = "gemini"


def test_generate_with_telemetry_tags_the_result_and_records_once(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "load_config", lambda: _FakeConfig())

    recorded: list[None] = []
    monkeypatch.setattr(main_module, "record_generation", lambda: recorded.append(None))
    monkeypatch.setattr(main_module, "telemetry_enabled", lambda: False)

    work_calls: list[None] = []

    async def work() -> dict:
        work_calls.append(None)
        return {"tracks": []}

    result = asyncio.run(main_module._generate_with_telemetry(work))

    assert work_calls == [None]  # work() is invoked exactly once, however it retries internally
    assert recorded == [None]
    assert result["generation_meta"]["provider"] == "gemini"
    assert isinstance(result["generation_meta"]["duration_ms"], int)
    assert result["generation_meta"]["duration_ms"] >= 0
    assert result["generation_meta"]["stage_timings_ms"] == {}


def test_generate_with_telemetry_captures_stage_timings_recorded_during_work(
    monkeypatch,
) -> None:
    monkeypatch.setattr(main_module, "load_config", lambda: _FakeConfig())
    monkeypatch.setattr(main_module, "record_generation", lambda: None)
    monkeypatch.setattr(main_module, "telemetry_enabled", lambda: False)

    async def work() -> dict:
        record_stage_ms("ai_draft", 120)
        record_stage_ms("youtube_resolution", 45)
        return {"tracks": []}

    result = asyncio.run(main_module._generate_with_telemetry(work))

    assert result["generation_meta"]["stage_timings_ms"] == {
        "ai_draft": 120,
        "youtube_resolution": 45,
    }


def test_generate_with_telemetry_pings_only_when_opted_in(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "load_config", lambda: _FakeConfig())
    monkeypatch.setattr(main_module, "record_generation", lambda: None)

    async def work() -> dict:
        return {"tracks": []}

    # Opted out: no background task should be scheduled.
    monkeypatch.setattr(main_module, "telemetry_enabled", lambda: False)
    scheduled: list[object] = []
    monkeypatch.setattr(main_module.asyncio, "create_task", lambda coro: scheduled.append(coro))
    asyncio.run(main_module._generate_with_telemetry(work))
    assert scheduled == []

    # Opted in: a background task is scheduled (and must be awaited/closed to avoid a warning).
    monkeypatch.setattr(main_module, "telemetry_enabled", lambda: True)

    async def fake_report() -> None:
        return None

    monkeypatch.setattr(main_module, "report_playlist_generated", fake_report)
    asyncio.run(main_module._generate_with_telemetry(work))
    assert len(scheduled) == 1
    asyncio.run(scheduled[0])
