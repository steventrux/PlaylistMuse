from __future__ import annotations

import asyncio
import time

from backend import generation_runtime_core as core
from backend.config import AppConfig


def _config() -> AppConfig:
    return AppConfig(provider="gemini", api_key="key", model="gemini-2.5-flash")


def test_initial_guidance_empty_outside_llm_initial_stage() -> None:
    assert (
        asyncio.run(
            core._initial_reccobeats_guidance(_config(), "llm_replenishment", "chill songs")
        )
        == ""
    )
    assert (
        asyncio.run(
            core._initial_reccobeats_guidance(_config(), "llm_replacement", "chill songs")
        )
        == ""
    )


def test_initial_guidance_fails_open_when_anchor_interpretation_errors(monkeypatch) -> None:
    async def broken_anchors(config, prompt):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        "backend.reccobeats_anchors.interpret_reccobeats_anchors", broken_anchors
    )

    guidance = asyncio.run(
        core._initial_reccobeats_guidance(_config(), "llm_initial", "chill acoustic songs")
    )
    assert guidance == ""


def test_initial_guidance_returns_empty_when_no_anchors_found(monkeypatch) -> None:
    async def empty_anchors(config, prompt):
        return []

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("recommendation discovery should not run without anchors")

    monkeypatch.setattr(
        "backend.reccobeats_anchors.interpret_reccobeats_anchors", empty_anchors
    )
    monkeypatch.setattr(
        "backend.reccobeats_features.recommendation_candidates_from_tracks",
        fail_if_called,
    )

    guidance = asyncio.run(
        core._initial_reccobeats_guidance(_config(), "llm_initial", "an obscure request")
    )
    assert guidance == ""


def test_initial_guidance_grounds_prompt_in_recommended_tracks(monkeypatch) -> None:
    async def fake_anchors(config, prompt):
        assert prompt == "moody 80s synth pop"
        return [{"artist": "Tears for Fears", "title": "Mad World"}]

    async def fake_recommendations(anchors, *, limit, max_anchors):
        assert anchors == [{"artist": "Tears for Fears", "title": "Mad World"}]
        return [{"artist": "Yazoo", "title": "Only You", "source": "reccobeats"}]

    monkeypatch.setattr(
        "backend.reccobeats_anchors.interpret_reccobeats_anchors", fake_anchors
    )
    monkeypatch.setattr(
        "backend.reccobeats_features.recommendation_candidates_from_tracks",
        fake_recommendations,
    )

    guidance = asyncio.run(
        core._initial_reccobeats_guidance(_config(), "llm_initial", "moody 80s synth pop")
    )
    assert "RECCOBEATS DISCOVERY" in guidance
    assert "Yazoo" in guidance
    assert "Only You" in guidance


def test_initial_guidance_fast_path_adds_negligible_overhead(monkeypatch) -> None:
    """The common case (both calls succeed instantly) must not add noticeable latency."""

    async def fake_anchors(config, prompt):
        return [{"artist": "Anchor Artist", "title": "Anchor Song"}]

    async def fake_recommendations(anchors, *, limit, max_anchors):
        return [{"artist": "Rec Artist", "title": "Rec Song"}]

    monkeypatch.setattr(
        "backend.reccobeats_anchors.interpret_reccobeats_anchors", fake_anchors
    )
    monkeypatch.setattr(
        "backend.reccobeats_features.recommendation_candidates_from_tracks",
        fake_recommendations,
    )

    started = time.perf_counter()
    guidance = asyncio.run(
        core._initial_reccobeats_guidance(_config(), "llm_initial", "road trip rock")
    )
    elapsed = time.perf_counter() - started

    assert guidance
    assert elapsed < 0.3


def test_initial_guidance_is_skipped_entirely_for_seed_based_generation(
    monkeypatch,
) -> None:
    """Seed requests get real grounding from Last.fm; ReccoBeats' single-seed
    recommendation output was found to be genre-incoherent noise in a live comparative
    check (French-house and mainstream-pop seeds alike), so it isn't worth the latency."""

    async def fail_if_called(config, prompt):
        raise AssertionError("anchor interpretation should not run for seed-based generation")

    async def fail_if_called_recommendations(anchors, *, limit, max_anchors):
        raise AssertionError("ReccoBeats recommendation lookup should not run for seed-based generation")

    monkeypatch.setattr(
        "backend.reccobeats_anchors.interpret_reccobeats_anchors", fail_if_called
    )
    monkeypatch.setattr(
        "backend.reccobeats_features.recommendation_candidates_from_tracks",
        fail_if_called_recommendations,
    )

    guidance = asyncio.run(
        core._initial_reccobeats_guidance(
            _config(),
            "llm_initial",
            "Create a playlist from the seed song 'Bohemian Rhapsody' by Queen.",
            {"artist": "Queen", "title": "Bohemian Rhapsody", "kind": "seed"},
        )
    )
    assert guidance == ""


def test_initial_guidance_anchor_interpretation_has_a_hard_timeout(monkeypatch) -> None:
    """A hung/slow AI provider must not be allowed to stall the initial draft.

    `interpret_reccobeats_anchors` has no timeout of its own — it can try every model in
    `config.model_chain` (primary plus up to 8 fallbacks) at up to 45s each. This is an
    optional grounding step, so it must be capped far below that worst case.
    """
    monkeypatch.setattr(core, "INITIAL_ANCHOR_TIMEOUT_SECONDS", 0.05)

    async def hanging_anchors(config, prompt):
        await asyncio.sleep(5)
        return [{"artist": "Too Slow", "title": "Never Arrives"}]

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("recommendation discovery should not run after a timeout")

    monkeypatch.setattr(
        "backend.reccobeats_anchors.interpret_reccobeats_anchors", hanging_anchors
    )
    monkeypatch.setattr(
        "backend.reccobeats_features.recommendation_candidates_from_tracks",
        fail_if_called,
    )

    started = time.perf_counter()
    guidance = asyncio.run(
        core._initial_reccobeats_guidance(_config(), "llm_initial", "road trip rock")
    )
    elapsed = time.perf_counter() - started

    assert guidance == ""
    # Generous margin for sandbox scheduling jitter — the real regression this guards
    # against is the timeout not firing at all, which would leave elapsed near 5s.
    assert elapsed < 2.0


def test_initial_guidance_worst_case_is_bounded_not_multiplied(monkeypatch) -> None:
    """Total worst-case latency is the sum of the two bounded phases, not a larger multiple.

    Regression guard: if a future change wraps the whole function in its own retry loop or
    adds an extra timeout layer on top of the two existing bounds, this catches the
    added tail latency before it reaches production.
    """
    monkeypatch.setattr(core, "INITIAL_ANCHOR_TIMEOUT_SECONDS", 0.05)

    async def slow_anchors(config, prompt):
        await asyncio.sleep(0.05)
        return [{"artist": "Anchor Artist", "title": "Anchor Song"}]

    async def slow_recommendations(anchors, *, limit, max_anchors):
        await asyncio.sleep(0.05)
        return []

    monkeypatch.setattr(
        "backend.reccobeats_anchors.interpret_reccobeats_anchors", slow_anchors
    )
    monkeypatch.setattr(
        "backend.reccobeats_features.recommendation_candidates_from_tracks",
        slow_recommendations,
    )

    started = time.perf_counter()
    guidance = asyncio.run(
        core._initial_reccobeats_guidance(_config(), "llm_initial", "road trip rock")
    )
    elapsed = time.perf_counter() - started

    assert guidance == ""  # no candidates returned
    # Two sequential ~0.05s phases, not a retried/multiplied total. Generous margin for
    # sandbox jitter — this guards against an accidental retry loop or extra timeout
    # layer, which would push elapsed well past this ceiling.
    assert elapsed < 2.0


def _patch_taste_memory_ready(monkeypatch) -> None:
    """Convenience for tests exercising the AI-call path: makes both gates upstream of
    the actual call (enabled + convergent data present) pass."""
    monkeypatch.setattr(
        "backend.local_taste_memory.generation_influence_enabled", lambda: True
    )
    monkeypatch.setattr(
        "backend.local_taste_memory.has_convergent_taste_memory", lambda: True
    )


def test_resolve_taste_memory_signal_returns_none_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.local_taste_memory.generation_influence_enabled", lambda: False
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("interpret_taste_signal should not run when disabled")

    monkeypatch.setattr("backend.local_taste_memory.interpret_taste_signal", fail_if_called)

    signal = asyncio.run(
        core._resolve_taste_memory_signal(_config(), "upbeat house set", "llm_initial")
    )

    assert signal is None


def test_resolve_taste_memory_signal_delegates_when_enabled(monkeypatch) -> None:
    _patch_taste_memory_ready(monkeypatch)

    async def fake_signal(config, prompt):
        assert prompt == "upbeat house set"
        return {"genre": ["house"], "mood": ["euphoric"]}

    monkeypatch.setattr("backend.local_taste_memory.interpret_taste_signal", fake_signal)

    signal = asyncio.run(
        core._resolve_taste_memory_signal(_config(), "upbeat house set", "llm_initial")
    )

    assert signal == {"genre": ["house"], "mood": ["euphoric"]}


def test_taste_memory_signal_context_var_round_trips() -> None:
    core.activate_taste_memory_signal({"genre": ["techno"], "mood": []})
    assert core.active_taste_memory_signal() == {"genre": ["techno"], "mood": []}
    core.activate_taste_memory_signal(None)
    assert core.active_taste_memory_signal() is None


def test_resolve_taste_memory_signal_fails_open_on_unexpected_error(monkeypatch) -> None:
    """A corrupt/mismatched local_taste_memory.json (e.g. a schema-validation error from
    generation_influence_enabled's underlying _load_memory) must never break generation."""

    def broken_enabled_check():
        raise ValueError("corrupt local_taste_memory.json")

    monkeypatch.setattr(
        "backend.local_taste_memory.generation_influence_enabled", broken_enabled_check
    )

    signal = asyncio.run(
        core._resolve_taste_memory_signal(_config(), "upbeat house set", "llm_initial")
    )

    assert signal is None


def test_resolve_taste_memory_signal_scoped_to_llm_initial_stage(monkeypatch) -> None:
    """Fix 4: the design spec scoped this feature to initial text-prompt generation only
    -- seed-mode generation and the replace-track endpoint were explicit non-goals. The
    gate must short-circuit before any I/O, so interpret_taste_signal must never even be
    called for an out-of-scope stage."""
    _patch_taste_memory_ready(monkeypatch)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("interpret_taste_signal should not run outside llm_initial")

    monkeypatch.setattr("backend.local_taste_memory.interpret_taste_signal", fail_if_called)

    for stage in ("llm_replacement", "llm_replenishment", "something_else"):
        signal = asyncio.run(
            core._resolve_taste_memory_signal(_config(), "upbeat house set", stage)
        )
        assert signal is None


def test_resolve_taste_memory_signal_scoped_away_from_seed_generation(monkeypatch) -> None:
    """Fix 4: seed-mode generation is an explicit non-goal, even when stage is
    llm_initial (seed generation also runs its interpretation under that stage name)."""
    _patch_taste_memory_ready(monkeypatch)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("interpret_taste_signal should not run for seed generation")

    monkeypatch.setattr("backend.local_taste_memory.interpret_taste_signal", fail_if_called)

    signal = asyncio.run(
        core._resolve_taste_memory_signal(
            _config(), "upbeat house set", "llm_initial", is_seed_generation=True
        )
    )

    assert signal is None


def test_resolve_taste_memory_signal_skips_call_without_convergent_data(monkeypatch) -> None:
    """Fix 5a: on a fresh install or one still below the convergence threshold (the
    common case), the AI call must be skipped entirely -- its result would be discarded
    downstream by taste_memory_guidance anyway."""
    monkeypatch.setattr(
        "backend.local_taste_memory.generation_influence_enabled", lambda: True
    )
    monkeypatch.setattr(
        "backend.local_taste_memory.has_convergent_taste_memory", lambda: False
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError(
            "interpret_taste_signal should not run without convergent taste memory"
        )

    monkeypatch.setattr("backend.local_taste_memory.interpret_taste_signal", fail_if_called)

    signal = asyncio.run(
        core._resolve_taste_memory_signal(_config(), "upbeat house set", "llm_initial")
    )

    assert signal is None


def test_resolve_taste_memory_signal_uses_a_three_second_wait_for_timeout(
    monkeypatch,
) -> None:
    """Fix 5b: the call must be wrapped in asyncio.wait_for(..., timeout=3.0), and a
    timeout must degrade to None rather than raising. Verified via a fake wait_for that
    raises TimeoutError immediately, rather than an actual multi-second sleep, to keep
    this test fast and non-flaky."""
    _patch_taste_memory_ready(monkeypatch)

    async def never_called_signal(config, prompt):
        raise AssertionError("interpret_taste_signal's coroutine must not be awaited here")

    monkeypatch.setattr(
        "backend.local_taste_memory.interpret_taste_signal", never_called_signal
    )

    captured_timeout = {}

    async def fake_wait_for(awaitable, timeout):
        captured_timeout["value"] = timeout
        awaitable.close()  # avoid a "coroutine was never awaited" warning
        raise TimeoutError()

    monkeypatch.setattr(core.asyncio, "wait_for", fake_wait_for)

    signal = asyncio.run(
        core._resolve_taste_memory_signal(_config(), "upbeat house set", "llm_initial")
    )

    assert signal is None
    assert captured_timeout["value"] == 3.0
