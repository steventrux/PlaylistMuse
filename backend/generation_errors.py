"""Local, persistent tally of generation failures, by exception type.

Uses the raised exception's class name as the category ("ValueError",
"TimeoutError", ...) rather than inventing a taxonomy -- it's the most honest "which
kind of error" label already available at every existing except block, with no new
guesswork about what counts as a "provider" error vs a "validation" error.
"""

from __future__ import annotations

from backend.config import DATA_DIR
from backend.storage import read_json_object, write_secure_json

GENERATION_ERRORS_PATH = DATA_DIR / "generation_errors.json"


def error_breakdown() -> dict[str, int]:
    """Return the current tally without changing it."""
    values = read_json_object(GENERATION_ERRORS_PATH)
    return {
        str(category): int(count)
        for category, count in values.items()
        if isinstance(count, int) and count > 0
    }


def record_generation_error(error: BaseException) -> None:
    """Increment the count for this exception's class name."""
    category = type(error).__name__
    counts = error_breakdown()
    counts[category] = counts.get(category, 0) + 1
    write_secure_json(GENERATION_ERRORS_PATH, counts)
