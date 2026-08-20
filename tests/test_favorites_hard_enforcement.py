from __future__ import annotations

import asyncio

import pytest

from backend import generation_runtime, llm
from backend.favorites import activate_favorite_artist_allowlist
from backend.metadata_validation import MetadataConstraints, activate_constraints, active_constraints
from backend.prompt_validation import PromptAssessment
from backend.recording_variants import RecordingVariantPolicy


@pytest.fixture(autouse=True)
def _reset_generation_contextvars():
    # These tests call the real generate_playlist_draft(), which sets process-wide
    # ContextVars with no per-test isolation (no conftest fixture resets them) --
    # leaving a non-empty allowed_artists behind would leak into unrelated tests
    # that run later in the same pytest process without setting their own.
    yield
    activate_favorite_artist_allowlist([])
    activate_constraints(MetadataConstraints())


def _stub_interpretation_pipeline(monkeypatch, *, assessment: PromptAssessment | None = None):
    import backend.entity_resolution as entity_resolution
    import backend.prompt_validation as prompt_validation
    import backend.recording_variants as recording_variants

    async def fake_assess(config, request: str) -> PromptAssessment:
        return assessment or PromptAssessment(status="valid", interpretation={})

    async def fake_recording_policy(config, request: str) -> RecordingVariantPolicy:
        return RecordingVariantPolicy()

    async def fake_canonicalize(payload):
        return payload or {}

    monkeypatch.setattr(prompt_validation, "assess_prompt", fake_assess)
    monkeypatch.setattr(recording_variants, "interpret_recording_policy", fake_recording_policy)
    monkeypatch.setattr(entity_resolution, "canonicalize_interpretation", fake_canonicalize)


def test_favorite_artist_allowlist_merges_into_constraints_during_llm_initial_stage(
    monkeypatch,
) -> None:
    # ContextVar writes made inside asyncio.run()'s Task don't propagate back out to
    # the caller's context, so activate + call + assert must all run in one coroutine.
    _stub_interpretation_pipeline(monkeypatch)

    async def fake_generate(config, submitted: str, count: int) -> dict:
        return {"title": "Test", "description": "", "tracks": []}

    monkeypatch.setattr(llm, "generate_playlist_draft", fake_generate)

    async def scenario() -> list[str]:
        activate_favorite_artist_allowlist(["AC/DC", "The Rolling Stones"])
        await generation_runtime.generate_playlist_draft(object(), "some prompt", 5)
        return active_constraints().allowed_artists

    assert asyncio.run(scenario()) == ["AC/DC", "The Rolling Stones"]


def test_favorite_artist_lock_merges_an_explicit_style_requirement_into_creative_intent(
    monkeypatch,
) -> None:
    # When the artist pool is hard-locked to favorites, an explicit genre/style in the
    # prompt (e.g. "house") must also be checked against the resulting tracks --
    # otherwise the AI can be forced to pick genre-incompatible songs from the few
    # allowed artists with no validation catching it (see backend.creative_intent's
    # interpret_style_request docstring).
    import backend.creative_intent as creative_intent_module
    from backend.config import AppConfig

    _stub_interpretation_pipeline(monkeypatch)

    async def fake_style(config, prompt) -> creative_intent_module.CreativeIntent:
        return creative_intent_module.CreativeIntent(("house",), 0.9)

    monkeypatch.setattr(creative_intent_module, "interpret_style_request", fake_style)

    async def fake_generate(config, submitted: str, count: int) -> dict:
        return {"title": "Test", "description": "", "tracks": []}

    monkeypatch.setattr(llm, "generate_playlist_draft", fake_generate)

    async def scenario() -> creative_intent_module.CreativeIntent:
        activate_favorite_artist_allowlist(["AC/DC"])
        await generation_runtime.generate_playlist_draft(
            AppConfig(provider="openai", api_key="sk-test", model="model"),
            "Create a playlist house with my favorite artists",
            5,
        )
        return creative_intent_module.active_creative_intent()

    intent = asyncio.run(scenario())
    assert intent.requirements == ("house",)


def test_no_style_lookup_when_favorite_artist_lock_is_inactive(monkeypatch) -> None:
    import backend.creative_intent as creative_intent_module
    from backend.config import AppConfig

    _stub_interpretation_pipeline(monkeypatch)

    async def fail_style(config, prompt):
        raise AssertionError("style should not be looked up without an active favorite lock")

    monkeypatch.setattr(creative_intent_module, "interpret_style_request", fail_style)

    async def fake_generate(config, submitted: str, count: int) -> dict:
        return {"title": "Test", "description": "", "tracks": []}

    monkeypatch.setattr(llm, "generate_playlist_draft", fake_generate)

    async def scenario() -> None:
        activate_favorite_artist_allowlist([])
        await generation_runtime.generate_playlist_draft(
            AppConfig(provider="openai", api_key="sk-test", model="model"),
            "Create a playlist house",
            5,
        )

    asyncio.run(scenario())


def test_favorite_artist_allowlist_unions_with_an_interpreted_allowed_artist(
    monkeypatch,
) -> None:
    _stub_interpretation_pipeline(
        monkeypatch,
        assessment=PromptAssessment(
            status="valid",
            interpretation={
                "allowed_artists": ["Radiohead"],
                "field_confidence": {"allowed_artists": 0.95},
            },
        ),
    )

    async def fake_generate(config, submitted: str, count: int) -> dict:
        return {"title": "Test", "description": "", "tracks": []}

    monkeypatch.setattr(llm, "generate_playlist_draft", fake_generate)

    async def scenario() -> list[str]:
        activate_favorite_artist_allowlist(["AC/DC"])
        await generation_runtime.generate_playlist_draft(object(), "some prompt", 5)
        return active_constraints().allowed_artists

    assert asyncio.run(scenario()) == ["Radiohead", "AC/DC"]


def test_no_favorite_artist_allowlist_leaves_constraints_unchanged(monkeypatch) -> None:
    _stub_interpretation_pipeline(monkeypatch)

    async def fake_generate(config, submitted: str, count: int) -> dict:
        return {"title": "Test", "description": "", "tracks": []}

    monkeypatch.setattr(llm, "generate_playlist_draft", fake_generate)

    async def scenario() -> list[str]:
        activate_favorite_artist_allowlist([])
        await generation_runtime.generate_playlist_draft(object(), "some prompt", 5)
        return active_constraints().allowed_artists

    assert asyncio.run(scenario()) == []
