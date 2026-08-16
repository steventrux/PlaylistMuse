"""Local, persistent lifetime counter of successful playlist generations.

Unlike the playlist library (which only counts *saved* playlists and shrinks when a
playlist is deleted), this counter increments on every successful generation and never
decreases -- it is the most accurate local answer to "how many playlists has this
installation generated". It also keeps a month-by-month breakdown of the same total,
so the "playlists over time" chart on the statistics page sums to the same number as
the headline figure instead of only reflecting the (smaller) set of saved playlists.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.config import DATA_DIR
from backend.storage import read_json_object, write_secure_json

GENERATION_COUNTER_PATH = DATA_DIR / "generation_counter.json"


def total_generations() -> int:
    """Return the current lifetime total without incrementing it."""
    values = read_json_object(GENERATION_COUNTER_PATH)
    return max(0, int(values.get("total", 0) or 0))


def generations_by_month() -> dict[str, int]:
    """Return the lifetime total broken down by the "YYYY-MM" it happened in."""
    by_month = read_json_object(GENERATION_COUNTER_PATH).get("by_month")
    if not isinstance(by_month, dict):
        return {}
    return {
        str(month): int(count)
        for month, count in by_month.items()
        if isinstance(count, int) and count > 0
    }


def record_generation() -> int:
    """Increment the lifetime total (and this month's count) and return the new total."""
    values = read_json_object(GENERATION_COUNTER_PATH)
    total = max(0, int(values.get("total", 0) or 0)) + 1

    by_month = values.get("by_month")
    if not isinstance(by_month, dict):
        by_month = {}
    month_key = datetime.now(UTC).strftime("%Y-%m")
    by_month[month_key] = int(by_month.get(month_key, 0) or 0) + 1

    write_secure_json(GENERATION_COUNTER_PATH, {"total": total, "by_month": by_month})
    return total
