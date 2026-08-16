from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import backend.generation_errors as generation_errors
import backend.main as main_module


def test_generate_route_records_a_value_error(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "generation_errors.json"
    monkeypatch.setattr(generation_errors, "GENERATION_ERRORS_PATH", path)

    async def failing_generate(prompt, count, options):
        raise ValueError("Describe the playlist you want.")

    monkeypatch.setattr(main_module, "_generate", failing_generate)

    response = TestClient(main_module.app).post(
        "/api/playlists/generate",
        json={"prompt": "anything", "track_count": 10, "options": {}},
    )

    assert response.status_code == 400
    assert generation_errors.error_breakdown() == {"ValueError": 1}


def test_generate_route_records_an_unexpected_error(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "generation_errors.json"
    monkeypatch.setattr(generation_errors, "GENERATION_ERRORS_PATH", path)

    async def failing_generate(prompt, count, options):
        raise RuntimeError("the AI provider timed out")

    monkeypatch.setattr(main_module, "_generate", failing_generate)

    response = TestClient(main_module.app).post(
        "/api/playlists/generate",
        json={"prompt": "anything", "track_count": 10, "options": {}},
    )

    assert response.status_code == 502
    assert generation_errors.error_breakdown() == {"RuntimeError": 1}
