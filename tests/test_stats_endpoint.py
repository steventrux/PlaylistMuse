from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import backend.generation_counter as generation_counter
import backend.generation_errors as generation_errors
import backend.main as main_module
import backend.playlist_stats as playlist_stats


def test_stats_endpoint_returns_general_and_nerd_sections(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(playlist_stats, "DATABASE_PATH", tmp_path / "playlists.db")
    monkeypatch.setattr(
        generation_counter, "GENERATION_COUNTER_PATH", tmp_path / "generation_counter.json"
    )
    monkeypatch.setattr(
        generation_errors, "GENERATION_ERRORS_PATH", tmp_path / "generation_errors.json"
    )

    response = TestClient(main_module.app).get("/api/stats")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"general", "nerd"}
    assert payload["general"]["total_generated"] == 0
    assert payload["general"]["top_genres"] == []
    assert payload["general"]["top_moods"] == []
    assert payload["nerd"]["avg_generation_ms"] is None
    assert payload["nerd"]["error_breakdown"] == {}
    assert payload["nerd"]["total_errors"] == 0
