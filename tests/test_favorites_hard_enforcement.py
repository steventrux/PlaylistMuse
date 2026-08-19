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
