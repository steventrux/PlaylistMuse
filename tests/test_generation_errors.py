from __future__ import annotations

from pathlib import Path

import backend.generation_errors as generation_errors


def test_generation_errors_are_tallied_by_exception_type(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "generation_errors.json"
    monkeypatch.setattr(generation_errors, "GENERATION_ERRORS_PATH", path)

    assert generation_errors.error_breakdown() == {}

    generation_errors.record_generation_error(ValueError("bad request"), provider="gemini")
    generation_errors.record_generation_error(ValueError("another one"), provider="gemini")
    generation_errors.record_generation_error(TimeoutError("slow provider"), provider="openai")

    assert generation_errors.error_breakdown() == {
        "gemini": {"ValueError": 2},
        "openai": {"TimeoutError": 1},
    }


def test_generation_errors_default_to_unknown_provider(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "generation_errors.json"
    monkeypatch.setattr(generation_errors, "GENERATION_ERRORS_PATH", path)

    generation_errors.record_generation_error(ValueError("bad request"))

    assert generation_errors.error_breakdown() == {"unknown": {"ValueError": 1}}


def test_legacy_flat_error_shape_is_skipped_not_misattributed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from backend.storage import write_secure_json

    path = tmp_path / "generation_errors.json"
    monkeypatch.setattr(generation_errors, "GENERATION_ERRORS_PATH", path)
    write_secure_json(path, {"ValueError": 3})

    assert generation_errors.error_breakdown() == {}
