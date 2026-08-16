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

    generation_errors.record_generation_error(ValueError("bad request"))
    generation_errors.record_generation_error(ValueError("another one"))
    generation_errors.record_generation_error(TimeoutError("slow provider"))

    assert generation_errors.error_breakdown() == {"ValueError": 2, "TimeoutError": 1}
