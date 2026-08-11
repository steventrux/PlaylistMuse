import io
import json
import re
import zipfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

import backend.diagnostics as diagnostics


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


def test_sanitize_data_redacts_sensitive_fields_recursively() -> None:
    payload = {
        "provider": "openai",
        "api_key": "secret-value",
        "nested": {
            "refresh_token": "refresh-value",
            "message": "secret-value should disappear",
        },
    }

    sanitized = diagnostics.sanitize_data(payload, secret_values=("secret-value",))

    assert sanitized["provider"] == "openai"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["nested"]["refresh_token"] == "[REDACTED]"
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
