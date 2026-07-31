from __future__ import annotations

from pathlib import Path

from backend.storage import delete_file, read_json_object, write_secure_json


def test_read_json_object_handles_missing_invalid_and_non_object_files(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    assert read_json_object(path) == {}

    path.write_text("not-json", encoding="utf-8")
    assert read_json_object(path) == {}

    path.write_text("[]", encoding="utf-8")
    assert read_json_object(path) == {}


def test_write_secure_json_is_atomic_and_uses_restrictive_permissions(
    tmp_path: Path,
) -> None:
    path = tmp_path / "settings.json"
    temporary = tmp_path / "settings.tmp"

    write_secure_json(
        path,
        {"client_id": "test", "enabled": True},
        temporary_path=temporary,
    )

    assert read_json_object(path) == {"client_id": "test", "enabled": True}
    assert not temporary.exists()
    assert path.stat().st_mode & 0o777 == 0o600


def test_delete_file_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    path.write_text("{}", encoding="utf-8")

    delete_file(path)
    delete_file(path)

    assert not path.exists()
