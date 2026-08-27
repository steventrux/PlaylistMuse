from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi import BackgroundTasks
from fastapi.testclient import TestClient

import backend.local_taste_memory as local_taste_memory_module
from backend.application import app
from backend.local_taste_memory import LocalTasteEntry, LocalTasteMemory


def sample_playlist() -> dict:
    return {
        "name": "Sunset Drive",
        "description": "Warm synths for a coastal evening drive.",
        "prompt": "Chill synthwave for a sunset drive along the coast.",
        "tracks": [
            {"video_id": "abc123", "title": "Track one", "artists": "Artist one"},
            {"video_id": "def456", "title": "Track two", "artists": "Artist two"},
        ],
    }


def test_entry_schema_defaults_to_pending_with_no_guidance() -> None:
    entry = LocalTasteEntry(
        id="entry-1",
        created_at="2026-08-27T12:00:00+00:00",
        flow="generation",
        prompt_summary="Chill synthwave for a sunset drive along the coast.",
    )

    assert entry.status == "pending"
    assert entry.distilled_guidance is None
    assert entry.tags == {}
    assert entry.options == {}


def test_memory_round_trips_through_storage(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        local_taste_memory_module, "LOCAL_TASTE_MEMORY_PATH", tmp_path / "taste.json"
    )
    entry = LocalTasteEntry(
        id="entry-1",
        created_at="2026-08-27T12:00:00+00:00",
        flow="generation",
        prompt_summary="Example.",
        status="captured",
        distilled_guidance="Kept energy steady rather than peaking early.",
    )
    memory = LocalTasteMemory(entries=[entry])

    local_taste_memory_module._save_memory(memory)
    reloaded = local_taste_memory_module._load_memory()

    assert reloaded.entries[0].distilled_guidance == entry.distilled_guidance
    assert reloaded.entries[0].status == "captured"


def test_capture_endpoint_returns_before_distillation_runs(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        local_taste_memory_module, "LOCAL_TASTE_MEMORY_PATH", tmp_path / "taste.json"
    )

    distill_called = False

    async def slow_distill(entry_id, prompt_summary, playlist):
        nonlocal distill_called
        distill_called = True

    monkeypatch.setattr(
        local_taste_memory_module, "_distill_local_taste_entry", slow_distill
    )

    request = local_taste_memory_module.LocalTasteCaptureRequest(
        playlist=sample_playlist(),
        generation_request={"mode": "prompt", "prompt": sample_playlist()["prompt"]},
    )
    background_tasks = BackgroundTasks()

    payload = asyncio.run(
        local_taste_memory_module.capture_local_taste(request, background_tasks)
    )

    assert payload["status"] == "pending"
    assert payload["distilled_guidance"] is None
    assert not distill_called, (
        "the endpoint must return before the background distillation task runs"
    )

    asyncio.run(background_tasks())
    assert distill_called


def test_distillation_captures_guidance_and_tags(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        local_taste_memory_module, "LOCAL_TASTE_MEMORY_PATH", tmp_path / "taste.json"
    )

    async def fake_suggest_tags(config, playlist):
        return {"genre": ["Synthwave"], "mood": ["Nostalgic"], "period": ["2010s"], "custom": []}

    async def fake_distill(config, prompt_summary, playlist, tags):
        return "Leaned into a steady, unhurried pace rather than building to a peak."

    monkeypatch.setattr(local_taste_memory_module, "suggest_playlist_tags", fake_suggest_tags)
    monkeypatch.setattr(local_taste_memory_module, "_distill_guidance", fake_distill)
    monkeypatch.setattr(local_taste_memory_module, "load_config", lambda: SimpleNamespace())

    client = TestClient(app)
    created = client.post(
        "/api/quality/local-feedback",
        json={
            "playlist": sample_playlist(),
            "generation_request": {"mode": "prompt", "prompt": sample_playlist()["prompt"]},
        },
    ).json()

    for _ in range(50):
        listed = client.get("/api/quality/local-feedback").json()["entries"]
        entry = next(item for item in listed if item["id"] == created["id"])
        if entry["status"] == "captured":
            break
        time.sleep(0.02)
    else:
        raise AssertionError("Background distillation never completed")

    assert entry["distilled_guidance"] == (
        "Leaned into a steady, unhurried pace rather than building to a peak."
    )
    assert entry["tags"]["genre"] == ["Synthwave"]


def test_empty_but_valid_guidance_is_captured_not_failed(monkeypatch, tmp_path: Path) -> None:
    """A legitimate 'nothing notable beyond hard constraints' answer is success,
    not failure -- the same fix already applied to suggest_playlist_tags today,
    applied consistently here.
    """
    monkeypatch.setattr(
        local_taste_memory_module, "LOCAL_TASTE_MEMORY_PATH", tmp_path / "taste.json"
    )

    async def fake_suggest_tags(config, playlist):
        return {"genre": [], "mood": [], "period": [], "custom": []}

    async def fake_distill(config, prompt_summary, playlist, tags):
        return ""

    monkeypatch.setattr(local_taste_memory_module, "suggest_playlist_tags", fake_suggest_tags)
    monkeypatch.setattr(local_taste_memory_module, "_distill_guidance", fake_distill)
    monkeypatch.setattr(local_taste_memory_module, "load_config", lambda: SimpleNamespace())

    client = TestClient(app)
    created = client.post(
        "/api/quality/local-feedback",
        json={
            "playlist": sample_playlist(),
            "generation_request": {"mode": "prompt", "prompt": sample_playlist()["prompt"]},
        },
    ).json()

    for _ in range(50):
        listed = client.get("/api/quality/local-feedback").json()["entries"]
        entry = next(item for item in listed if item["id"] == created["id"])
        if entry["status"] != "pending":
            break
        time.sleep(0.02)
    else:
        raise AssertionError("Background distillation never completed")

    assert entry["status"] == "captured"
    assert entry["distilled_guidance"] is None


def test_distillation_failure_stays_visible_not_silently_dropped(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        local_taste_memory_module, "LOCAL_TASTE_MEMORY_PATH", tmp_path / "taste.json"
    )

    async def fake_suggest_tags(config, playlist):
        return {"genre": [], "mood": [], "period": [], "custom": []}

    async def failing_distill(config, prompt_summary, playlist, tags):
        raise ValueError("The AI provider returned no valid guidance.")

    monkeypatch.setattr(local_taste_memory_module, "suggest_playlist_tags", fake_suggest_tags)
    monkeypatch.setattr(local_taste_memory_module, "_distill_guidance", failing_distill)
    monkeypatch.setattr(local_taste_memory_module, "load_config", lambda: SimpleNamespace())

    client = TestClient(app)
    created = client.post(
        "/api/quality/local-feedback",
        json={
            "playlist": sample_playlist(),
            "generation_request": {"mode": "prompt", "prompt": sample_playlist()["prompt"]},
        },
    ).json()

    for _ in range(50):
        listed = client.get("/api/quality/local-feedback").json()["entries"]
        entry = next(item for item in listed if item["id"] == created["id"])
        if entry["status"] != "pending":
            break
        time.sleep(0.02)
    else:
        raise AssertionError("Background distillation never completed")

    assert entry["status"] == "distillation_failed"
    still_listed = client.get("/api/quality/local-feedback").json()["entries"]
    assert any(item["id"] == created["id"] for item in still_listed), (
        "a failed distillation must stay visible, never disappear"
    )


def test_background_task_updates_its_own_entry_without_disturbing_others(
    monkeypatch, tmp_path: Path
) -> None:
    """Regression-shaped test for the class of bug fixed today in
    playlist_library.py: updating one entry must never clobber a sibling entry
    that already finished (or is still pending) in the same store.
    """
    monkeypatch.setattr(
        local_taste_memory_module, "LOCAL_TASTE_MEMORY_PATH", tmp_path / "taste.json"
    )
    other = LocalTasteEntry(
        id="other-entry",
        created_at="2026-08-27T12:00:00+00:00",
        flow="generation",
        prompt_summary="Unrelated request.",
        status="captured",
        distilled_guidance="Already finished before this test started.",
    )
    local_taste_memory_module._save_memory(LocalTasteMemory(entries=[other]))

    async def fake_suggest_tags(config, playlist):
        return {"genre": ["Rock"], "mood": [], "period": [], "custom": []}

    async def fake_distill(config, prompt_summary, playlist, tags):
        return "A fresh, distinct guidance sentence."

    monkeypatch.setattr(local_taste_memory_module, "suggest_playlist_tags", fake_suggest_tags)
    monkeypatch.setattr(local_taste_memory_module, "_distill_guidance", fake_distill)
    monkeypatch.setattr(local_taste_memory_module, "load_config", lambda: SimpleNamespace())

    client = TestClient(app)
    created = client.post(
        "/api/quality/local-feedback",
        json={
            "playlist": sample_playlist(),
            "generation_request": {"mode": "prompt", "prompt": sample_playlist()["prompt"]},
        },
    ).json()

    for _ in range(50):
        listed = client.get("/api/quality/local-feedback").json()["entries"]
        by_id = {item["id"]: item for item in listed}
        if by_id[created["id"]]["status"] != "pending":
            break
        time.sleep(0.02)
    else:
        raise AssertionError("Background distillation never completed")

    assert by_id["other-entry"]["distilled_guidance"] == (
        "Already finished before this test started."
    )
    assert by_id[created["id"]]["distilled_guidance"] == "A fresh, distinct guidance sentence."


def test_delete_removes_entry_and_404s_on_unknown_id(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        local_taste_memory_module, "LOCAL_TASTE_MEMORY_PATH", tmp_path / "taste.json"
    )
    entry = LocalTasteEntry(
        id="entry-1",
        created_at="2026-08-27T12:00:00+00:00",
        flow="generation",
        prompt_summary="Example.",
        status="captured",
    )
    local_taste_memory_module._save_memory(LocalTasteMemory(entries=[entry]))

    client = TestClient(app)
    deleted = client.delete("/api/quality/local-feedback/entry-1")
    assert deleted.status_code == 204
    assert client.get("/api/quality/local-feedback").json()["entries"] == []

    missing = client.delete("/api/quality/local-feedback/entry-1")
    assert missing.status_code == 404


def test_capture_rejects_empty_track_list(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        local_taste_memory_module, "LOCAL_TASTE_MEMORY_PATH", tmp_path / "taste.json"
    )
    client = TestClient(app)
    response = client.post(
        "/api/quality/local-feedback",
        json={"playlist": {"name": "Empty", "tracks": []}, "generation_request": None},
    )
    assert response.status_code == 422


def test_capture_stores_a_playlist_snapshot_for_later_retry(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        local_taste_memory_module, "LOCAL_TASTE_MEMORY_PATH", tmp_path / "taste.json"
    )

    async def slow_distill(entry_id, prompt_summary, playlist):
        return None

    monkeypatch.setattr(
        local_taste_memory_module, "_distill_local_taste_entry", slow_distill
    )

    client = TestClient(app)
    created = client.post(
        "/api/quality/local-feedback",
        json={"playlist": sample_playlist(), "generation_request": None},
    ).json()

    assert created["playlist"] == sample_playlist()
    stored = local_taste_memory_module._load_memory().entries[0]
    assert stored.playlist == sample_playlist()


def test_retry_reruns_distillation_from_the_stored_snapshot(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        local_taste_memory_module, "LOCAL_TASTE_MEMORY_PATH", tmp_path / "taste.json"
    )
    failed = LocalTasteEntry(
        id="entry-1",
        created_at="2026-08-27T12:00:00+00:00",
        flow="generation",
        prompt_summary="Chill synthwave for a sunset drive along the coast.",
        status="distillation_failed",
        playlist=sample_playlist(),
    )
    local_taste_memory_module._save_memory(LocalTasteMemory(entries=[failed]))

    async def fake_suggest_tags(config, playlist):
        return {"genre": ["Synthwave"], "mood": [], "period": [], "custom": []}

    async def fake_distill(config, prompt_summary, playlist, tags):
        return "Retried successfully this time."

    monkeypatch.setattr(local_taste_memory_module, "suggest_playlist_tags", fake_suggest_tags)
    monkeypatch.setattr(local_taste_memory_module, "_distill_guidance", fake_distill)
    monkeypatch.setattr(local_taste_memory_module, "load_config", lambda: SimpleNamespace())

    client = TestClient(app)
    response = client.post("/api/quality/local-feedback/entry-1/retry")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "captured"
    assert payload["distilled_guidance"] == "Retried successfully this time."
    assert payload["tags"]["genre"] == ["Synthwave"]


def test_retry_404s_on_unknown_entry(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        local_taste_memory_module, "LOCAL_TASTE_MEMORY_PATH", tmp_path / "taste.json"
    )
    client = TestClient(app)
    response = client.post("/api/quality/local-feedback/unknown-id/retry")
    assert response.status_code == 404


def test_retry_422s_when_no_snapshot_was_stored(tmp_path: Path, monkeypatch) -> None:
    """Entries captured before this field existed have no playlist snapshot --
    retry cannot work for them and must fail clearly, not silently no-op.
    """
    monkeypatch.setattr(
        local_taste_memory_module, "LOCAL_TASTE_MEMORY_PATH", tmp_path / "taste.json"
    )
    legacy = LocalTasteEntry(
        id="legacy-entry",
        created_at="2026-08-27T12:00:00+00:00",
        flow="generation",
        prompt_summary="Example.",
        status="distillation_failed",
    )
    local_taste_memory_module._save_memory(LocalTasteMemory(entries=[legacy]))

    client = TestClient(app)
    response = client.post("/api/quality/local-feedback/legacy-entry/retry")
    assert response.status_code == 422


def test_generation_influence_defaults_to_enabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        local_taste_memory_module, "LOCAL_TASTE_MEMORY_PATH", tmp_path / "taste.json"
    )
    assert local_taste_memory_module.generation_influence_enabled() is True


def test_settings_endpoint_round_trips(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        local_taste_memory_module, "LOCAL_TASTE_MEMORY_PATH", tmp_path / "taste.json"
    )
    client = TestClient(app)

    response = client.get("/api/quality/local-feedback/settings")
    assert response.status_code == 200
    assert response.json() == {"generation_influence_enabled": True}

    response = client.put(
        "/api/quality/local-feedback/settings",
        json={"generation_influence_enabled": False},
    )
    assert response.status_code == 200
    assert response.json() == {"generation_influence_enabled": False}
    assert local_taste_memory_module.generation_influence_enabled() is False


def test_interpret_taste_signal_parses_genre_and_mood(monkeypatch) -> None:
    async def fake_request(config, prompt, *, system_prompt, max_tokens):
        return '{"genre": ["house", "house"], "mood": ["euphoric"]}'

    monkeypatch.setattr(local_taste_memory_module, "request_structured_json", fake_request)

    signal = asyncio.run(
        local_taste_memory_module.interpret_taste_signal(SimpleNamespace(), "upbeat house set")
    )

    assert signal == {"genre": ["house"], "mood": ["euphoric"]}


def test_interpret_taste_signal_returns_none_on_provider_failure(monkeypatch) -> None:
    async def failing_request(config, prompt, *, system_prompt, max_tokens):
        raise ValueError("boom")

    monkeypatch.setattr(local_taste_memory_module, "request_structured_json", failing_request)

    signal = asyncio.run(
        local_taste_memory_module.interpret_taste_signal(SimpleNamespace(), "anything")
    )

    assert signal is None


def test_interpret_taste_signal_returns_none_on_malformed_json(monkeypatch) -> None:
    async def malformed_request(config, prompt, *, system_prompt, max_tokens):
        return "not json at all"

    monkeypatch.setattr(local_taste_memory_module, "request_structured_json", malformed_request)

    signal = asyncio.run(
        local_taste_memory_module.interpret_taste_signal(SimpleNamespace(), "anything")
    )

    assert signal is None
