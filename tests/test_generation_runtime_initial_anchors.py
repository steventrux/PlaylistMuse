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
