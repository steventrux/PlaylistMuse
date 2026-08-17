"""Per-request generation stage timing, accumulated for the life of one request.

Complements the log-only timing already emitted by generation_runtime_core.py's
_log_stage(): this module lets that same data be persisted into generation_meta
and later aggregated on the statistics page, without changing what gets logged.
"""

from __future__ import annotations

from contextvars import ContextVar

_STAGE_TIMINGS: ContextVar[dict[str, float] | None] = ContextVar(
    "_STAGE_TIMINGS", default=None
)


def reset_stage_timings() -> None:
    """Start a fresh accumulator for one top-level generation request."""
    _STAGE_TIMINGS.set({})


def record_stage_ms(stage: str, elapsed_ms: float) -> None:
    """Add elapsed time to a named stage; a no-op if no request is being tracked."""
    timings = _STAGE_TIMINGS.get()
    if timings is None:
        return
    timings[stage] = timings.get(stage, 0.0) + elapsed_ms


def stage_timings_snapshot() -> dict[str, int]:
    """Return the accumulated per-stage totals in milliseconds, rounded."""
    timings = _STAGE_TIMINGS.get()
    return {stage: round(value) for stage, value in timings.items()} if timings else {}
