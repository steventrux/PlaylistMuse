"""Process-lifetime cache hit/miss counters.

Not persisted -- these answer "how effective are the caches during this uptime",
not a permanent historical record. Reset on every restart along with the
process-lifetime state everything else here already has.
"""

from __future__ import annotations

from collections import Counter

_HITS: Counter[str] = Counter()
_MISSES: Counter[str] = Counter()


def record_hit(cache_name: str) -> None:
    _HITS[cache_name] += 1


def record_miss(cache_name: str) -> None:
    _MISSES[cache_name] += 1


def snapshot() -> dict[str, dict[str, int]]:
    names = set(_HITS) | set(_MISSES)
    return {name: {"hits": _HITS[name], "misses": _MISSES[name]} for name in names}
