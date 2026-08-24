import io
import json
import logging
import re
import zipfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

import backend.diagnostics as diagnostics
import backend.generation_counter as generation_counter
from backend import cache_metrics
from backend.application import app
from backend.playlist_library import PlaylistLibrary


@pytest.fixture
def _isolated_playlistmuse_logger():
    """Reset the shared "playlistmuse" logger's handlers around a test.

    configure_diagnostics_logging() is idempotent (it returns early once any handler
    is tagged _playlistmuse_diagnostics), so re-testing it requires a clean slate --
    otherwise it would just return the module-import-time logger untouched.
    """
    logger = logging.getLogger(diagnostics.LOGGER_NAME)
    original_handlers = list(logger.handlers)
    logger.handlers = []
    yield logger
    logger.handlers = original_handlers


def test_configure_diagnostics_logging_adds_console_and_file_handlers(
    tmp_path, monkeypatch, _isolated_playlistmuse_logger
) -> None:
    monkeypatch.setattr(diagnostics, "LOG_DIR", tmp_path)
    monkeypatch.setattr(diagnostics, "LOG_PATH", tmp_path / "playlistmuse.log")

    logger = diagnostics.configure_diagnostics_logging()

    console_handlers = [h for h in logger.handlers if type(h) is logging.StreamHandler]
    file_handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(console_handlers) == 1
    assert len(file_handlers) == 1
    assert all(
        any(isinstance(f, diagnostics._SanitizingFilter) for f in handler.filters)
        for handler in logger.handlers
    )


def test_configure_diagnostics_logging_is_idempotent(
    tmp_path, monkeypatch, _isolated_playlistmuse_logger
) -> None:
    monkeypatch.setattr(diagnostics, "LOG_DIR", tmp_path)
    monkeypatch.setattr(diagnostics, "LOG_PATH", tmp_path / "playlistmuse.log")

    diagnostics.configure_diagnostics_logging()
    diagnostics.configure_diagnostics_logging()

    assert len(_isolated_playlistmuse_logger.handlers) == 2


def test_console_handler_redacts_secrets_like_the_file_handler(
    tmp_path, monkeypatch, capsys, _isolated_playlistmuse_logger
) -> None:
    monkeypatch.setattr(diagnostics, "LOG_DIR", tmp_path)
    monkeypatch.setattr(diagnostics, "LOG_PATH", tmp_path / "playlistmuse.log")

    logger = diagnostics.configure_diagnostics_logging()
    logger.info("Authorization: Bearer sk-or-v1-abcdefghijklmnop")

    captured = capsys.readouterr()
    assert "sk-or-v1-abcdefghijklmnop" not in captured.err
    assert "[REDACTED]" in captured.err


def test_sanitize_text_redacts_common_and_known_secrets() -> None:
    known_secret = "custom-secret-value-123"
    text = (
        "Authorization: Bearer abcdefghijklmnop "
        "api_key=custom-secret-value-123 "
        "sk-thisisalongsecretvalue "
        "https://example.test/?token=sensitive-token"
    )

    sanitized = diagnostics.sanitize_text(text, secret_values=(known_secret,))

    assert known_secret not in sanitized
    assert "abcdefghijklmnop" not in sanitized
    assert "sk-thisisalongsecretvalue" not in sanitized
    assert "sensitive-token" not in sanitized
    assert "[REDACTED]" in sanitized


def test_sanitize_data_redacts_secrets_but_keeps_safe_state_flags() -> None:
    payload = {
        "provider": "openai",
        "api_key": "secret-value",
        "api_key_configured": True,
        "nested": {
            "refresh_token": "refresh-value",
            "oauth_token_present": False,
            "message": "secret-value should disappear",
        },
    }

    sanitized = diagnostics.sanitize_data(payload, secret_values=("secret-value",))

    assert sanitized["provider"] == "openai"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["api_key_configured"] is True
    assert sanitized["nested"]["refresh_token"] == "[REDACTED]"
    assert sanitized["nested"]["oauth_token_present"] is False
    assert "secret-value" not in sanitized["nested"]["message"]


def test_new_error_reference_has_stable_public_format() -> None:
    reference = diagnostics.new_error_reference()

    assert re.fullmatch(r"PM-\d{8}-[A-F0-9]{6}", reference)


def test_diagnostic_archive_is_sanitized_twice_before_sharing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    secret = "locally-stored-secret"
    log_path = tmp_path / "playlistmuse.log"
    log_path.write_text(
        f"request failed password={secret} free-text={secret}\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(diagnostics, "LOG_PATH", log_path)
    monkeypatch.setattr(diagnostics, "LOG_BACKUP_COUNT", 1)
    monkeypatch.setattr(diagnostics, "_known_secret_values", lambda: (secret,))
    monkeypatch.setattr(
        diagnostics,
        "_diagnostic_payload",
        lambda: {
            "build": {"version": "0.2.1"},
            "api_key": secret,
            "message": f"known value {secret}",
        },
    )

    archive_bytes = diagnostics.build_diagnostic_archive()

    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        names = set(archive.namelist())
        metadata = json.loads(archive.read("diagnostics.json"))
        log_text = archive.read("logs/playlistmuse.log").decode("utf-8")

    assert {"diagnostics.json", "README.txt", "logs/playlistmuse.log"} <= names
    assert metadata["build"]["version"] == "0.2.1"
    assert metadata["api_key"] == "[REDACTED]"
    assert secret not in metadata["message"]
    assert secret not in log_text


def _diagnostic_test_app() -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def diagnostics_layer(request: Request, call_next):
        return await diagnostics.diagnostics_middleware(request, call_next)

    @app.get("/api/handled-failure")
    async def handled_failure() -> None:
        raise HTTPException(status_code=502, detail="Upstream service failed.")

    @app.get("/api/unhandled-failure")
    async def unhandled_failure() -> None:
        raise RuntimeError("Unexpected failure")

    return app


def test_handled_server_error_gets_reference(monkeypatch) -> None:
    monkeypatch.setattr(diagnostics, "new_error_reference", lambda: "PM-20260811-ABC123")
    client = TestClient(_diagnostic_test_app(), raise_server_exceptions=False)

    response = client.get("/api/handled-failure")

    assert response.status_code == 502
    assert response.headers[diagnostics.ERROR_REFERENCE_HEADER] == "PM-20260811-ABC123"
    assert response.json()["error_reference"] == "PM-20260811-ABC123"
    assert "Error reference: PM-20260811-ABC123" in response.json()["detail"]


def test_unhandled_server_error_gets_reference(monkeypatch) -> None:
    monkeypatch.setattr(diagnostics, "new_error_reference", lambda: "PM-20260811-DEF456")
    monkeypatch.setattr(diagnostics, "_log_exception", lambda *args, **kwargs: None)
    client = TestClient(_diagnostic_test_app(), raise_server_exceptions=False)

    response = client.get("/api/unhandled-failure")

    assert response.status_code == 500
    assert response.headers[diagnostics.ERROR_REFERENCE_HEADER] == "PM-20260811-DEF456"
    assert "Error reference: PM-20260811-DEF456" in response.json()["detail"]


def _patch_storage_paths(monkeypatch, tmp_path: Path, database_path: Path, log_path: Path):
    cache_one = tmp_path / "metadata_cache.sqlite3"
    cache_one.write_bytes(b"x" * 100)
    cache_two = tmp_path / "youtube_resolution_cache.sqlite3"
    cache_two.write_bytes(b"y" * 50)

    monkeypatch.setattr(diagnostics, "DATA_DIR", tmp_path)
    monkeypatch.setattr(diagnostics, "DATABASE_PATH", database_path)
    monkeypatch.setattr(diagnostics, "LOG_PATH", log_path)
    monkeypatch.setattr(diagnostics, "LOG_BACKUP_COUNT", 0)
    monkeypatch.setattr(
        diagnostics,
        "CACHE_FILES",
        (("Metadata validation", cache_one, 90), ("YouTube resolution", cache_two, 30)),
    )
    monkeypatch.setattr(
        generation_counter, "GENERATION_COUNTER_PATH", tmp_path / "generation_counter.json"
    )
    return cache_one, cache_two


def test_storage_endpoint_reports_database_logs_and_cache_sizes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "playlists.db"
    library = PlaylistLibrary(database_path)
    library.create(
        {
            "name": "Night drive",
            "tracks": [
                {"video_id": "a", "title": "One", "artists": "Artist"},
                {"video_id": "b", "title": "Two", "artists": "Artist"},
            ],
        }
    )
    log_path = tmp_path / "playlistmuse.log"
    log_path.write_text("log line\n", encoding="utf-8")

    cache_one, cache_two = _patch_storage_paths(monkeypatch, tmp_path, database_path, log_path)

    response = TestClient(app).get("/api/diagnostics/storage")

    assert response.status_code == 200
    payload = response.json()
    assert payload["database"]["playlist_count"] == 1
    assert payload["database"]["track_count"] == 2
    assert payload["caches_total_bytes"] == cache_one.stat().st_size + cache_two.stat().st_size
    assert len(payload["caches"]) == 2
    assert payload["logs"]["size_bytes"] == log_path.stat().st_size
    assert payload["data_dir_total_bytes"] >= payload["caches_total_bytes"]


def test_storage_endpoint_reports_cache_hit_miss_metrics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "playlists.db"
    PlaylistLibrary(database_path)
    log_path = tmp_path / "playlistmuse.log"
    log_path.write_text("log\n", encoding="utf-8")

    _patch_storage_paths(monkeypatch, tmp_path, database_path, log_path)
    before = cache_metrics.snapshot().get(
        "Metadata validation", {"hits": 0, "misses": 0}
    )
    cache_metrics.record_hit("Metadata validation")
    cache_metrics.record_hit("Metadata validation")
    cache_metrics.record_miss("Metadata validation")

    response = TestClient(app).get("/api/diagnostics/storage")

    assert response.status_code == 200
    metadata_cache = next(
        c for c in response.json()["caches"] if c["name"] == "Metadata validation"
    )
    assert metadata_cache["hits"] == before["hits"] + 2
    assert metadata_cache["misses"] == before["misses"] + 1
    assert 0 < metadata_cache["hit_rate"] < 1


def test_clear_cache_deletes_only_cache_files(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "playlists.db"
    PlaylistLibrary(database_path)
    log_path = tmp_path / "playlistmuse.log"
    log_path.write_text("log line\n", encoding="utf-8")

    cache_one, cache_two = _patch_storage_paths(monkeypatch, tmp_path, database_path, log_path)
    bytes_before = cache_one.stat().st_size + cache_two.stat().st_size

    response = TestClient(app).post("/api/diagnostics/storage/clear-cache")

    assert response.status_code == 200
    payload = response.json()
    assert payload["cleared"] is True
    assert payload["bytes_freed"] == bytes_before
    assert not cache_one.exists()
    assert not cache_two.exists()
    assert database_path.exists()
    assert log_path.exists()


def test_storage_estimate_projects_from_real_usage(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "playlists.db"
    PlaylistLibrary(database_path)
    log_path = tmp_path / "playlistmuse.log"
    log_path.write_text("log\n", encoding="utf-8")

    cache_one, cache_two = _patch_storage_paths(monkeypatch, tmp_path, database_path, log_path)
    monkeypatch.setattr(diagnostics, "_usage_days_active", lambda: 10)
    monkeypatch.setattr(diagnostics, "total_generations", lambda: 42)

    response = TestClient(app).get("/api/diagnostics/storage")

    assert response.status_code == 200
    payload = response.json()
    assert payload["usage"] == {
        "total_generations": 42,
        "days_active": 10,
        "estimate_reliable": True,
    }
    metadata_cache = next(c for c in payload["caches"] if c["name"] == "Metadata validation")
    assert metadata_cache["estimated_steady_state_bytes"] == round(
        cache_one.stat().st_size * (90 / 10)
    )
    youtube_cache = next(c for c in payload["caches"] if c["name"] == "YouTube resolution")
    assert youtube_cache["estimated_steady_state_bytes"] == round(
        cache_two.stat().st_size * (30 / 10)
    )
    assert payload["caches_estimated_steady_state_total_bytes"] == (
        metadata_cache["estimated_steady_state_bytes"]
        + youtube_cache["estimated_steady_state_bytes"]
    )


def test_storage_estimate_is_unreliable_with_too_little_usage_history(
    tmp_path: Path, monkeypatch
) -> None:
    database_path = tmp_path / "playlists.db"
    PlaylistLibrary(database_path)
    log_path = tmp_path / "playlistmuse.log"
    log_path.write_text("log\n", encoding="utf-8")

    cache_one, cache_two = _patch_storage_paths(monkeypatch, tmp_path, database_path, log_path)
    monkeypatch.setattr(diagnostics, "_usage_days_active", lambda: 1)
    monkeypatch.setattr(diagnostics, "total_generations", lambda: 2)

    response = TestClient(app).get("/api/diagnostics/storage")

    payload = response.json()
    assert payload["usage"]["estimate_reliable"] is False
    metadata_cache = next(c for c in payload["caches"] if c["name"] == "Metadata validation")
    assert metadata_cache["estimated_steady_state_bytes"] == round(
        cache_one.stat().st_size * 90
    )
