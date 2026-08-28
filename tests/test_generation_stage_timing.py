from contextvars import Context

from backend import generation_stage_timing as stage_timing


def test_snapshot_is_empty_without_a_reset() -> None:
    # Runs in a brand-new Context so the module's ContextVar is guaranteed to be at
    # its default, regardless of what earlier tests (or a real request) already did
    # in the process's main context.
    result = Context().run(stage_timing.stage_timings_snapshot)

    assert result == {}


def test_record_stage_ms_is_a_noop_without_a_reset() -> None:
    def scenario() -> dict[str, int]:
        stage_timing.record_stage_ms("llm_initial", 123)
        return stage_timing.stage_timings_snapshot()

    assert Context().run(scenario) == {}


def test_reset_then_record_accumulates_per_stage() -> None:
    def scenario() -> dict[str, int]:
        stage_timing.reset_stage_timings()
        stage_timing.record_stage_ms("llm_initial", 100)
        stage_timing.record_stage_ms("youtube_resolution", 50)
        stage_timing.record_stage_ms("youtube_resolution", 25.4)
        return stage_timing.stage_timings_snapshot()

    assert Context().run(scenario) == {"llm_initial": 100, "youtube_resolution": 75}


def test_reset_starts_a_fresh_accumulator() -> None:
    def scenario() -> dict[str, int]:
        stage_timing.reset_stage_timings()
        stage_timing.record_stage_ms("llm_initial", 100)
        stage_timing.reset_stage_timings()
        return stage_timing.stage_timings_snapshot()

    assert Context().run(scenario) == {}
