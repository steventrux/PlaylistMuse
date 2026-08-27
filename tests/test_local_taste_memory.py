from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

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

    client = TestClient(app)
    response = client.post(
        "/api/quality/local-feedback",
        json={
            "playlist": sample_playlist(),
            "generation_request": {"mode": "prompt", "prompt": sample_playlist()["prompt"]},
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["distilled_guidance"] is None
    assert not distill_called, (
        "the endpoint must return before the background distillation task runs"
    )


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
