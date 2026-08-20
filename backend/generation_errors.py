"""Local, persistent tally of generation failures, by provider and exception type.

Uses the raised exception's class name as the category ("ValueError",
"TimeoutError", ...) rather than inventing a taxonomy -- it's the most honest "which
kind of error" label already available at every existing except block, with no new
guesswork about what counts as a "provider" error vs a "validation" error.
"""

from __future__ import annotations

from backend.config import DATA_DIR
from backend.storage import read_json_object, write_secure_json

GENERATION_ERRORS_PATH = DATA_DIR / "generation_errors.json"


def error_breakdown() -> dict[str, dict[str, int]]:
    """Return the current tally, nested by provider, without changing it.

    Entries recorded before per-provider tracking was added used a flat
    {category: count} shape; those are silently skipped here rather than
    misattributed to a provider, consistent with how duration/provider data
    already only exists for playlists recorded after that tracking was added.
    """
    values = read_json_object(GENERATION_ERRORS_PATH)
    breakdown: dict[str, dict[str, int]] = {}
    for provider, counts in values.items():
        if not isinstance(counts, dict):
            continue
        provider_counts = {
            str(category): int(count)
            for category, count in counts.items()
            if isinstance(count, int) and count > 0
        }
        if provider_counts:
            breakdown[str(provider)] = provider_counts
    return breakdown


def record_generation_error(error: BaseException, provider: str = "unknown") -> None:
    """Increment the count for this exception's class name, under this provider."""
    category = type(error).__name__
    provider_key = str(provider).strip() or "unknown"
    breakdown = error_breakdown()
    provider_counts = breakdown.setdefault(provider_key, {})
    provider_counts[category] = provider_counts.get(category, 0) + 1
    write_secure_json(GENERATION_ERRORS_PATH, breakdown)
