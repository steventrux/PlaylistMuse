"""Small atomic JSON-storage helpers used by persistent configuration modules."""

from __future__ import annotations

import json
from contextlib import suppress
from pathlib import Path
from typing import Any


def read_json_object(path: Path) -> dict[str, Any]:
    """Read a JSON object, returning an empty object for missing or invalid files."""
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def write_secure_json(
    path: Path,
    payload: dict[str, Any],
    *,
    temporary_path: Path | None = None,
) -> None:
    """Atomically write a JSON object and restrict the temporary file permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = temporary_path or path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with suppress(OSError):
        temporary.chmod(0o600)
    temporary.replace(path)


def delete_file(path: Path) -> None:
    """Best-effort removal for local credential and pending-state files."""
    with suppress(OSError):
        path.unlink(missing_ok=True)
