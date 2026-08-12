from __future__ import annotations

import asyncio
import json

from backend import creative_intent
from backend.config import AppConfig
from backend.creative_intent import (
    CreativeIntent,
    activate_creative_intent,
    assess_creative_fit,
    creative_repair_prompt,
    intent_from_payload,
    interpret_creative_intent,
    reset_creative_intent,
)


def _config() -> AppConfig:
    return AppConfig(provider="openai", api_key="sk-test", model="test-model")


def _track(title: str) -> dict[str, str]:
    return {
        "artist": "Test Artist",
        "title": title,
        "description": "Generated description claiming perfect suitability.",
        "reason": "Generated reason claiming this is ideal for the requested mood.",
    }


def test_intent_payload_requires_explicit_high_confidence_requirements() -> None:
    active = intent_from_payload(
        {
            "requirements": ["high-energy listening context", "upbeat mood"],
            "confidence": 0.95,
        }
    )
    uncertain = intent_from_payload(
        {"requirements": ["high-energy listening context"], "confidence": 0.4}
    )

    assert active.active is True
    assert active.requirements == (
        "high-energy listening context",
        "upbeat mood",
    )
    assert uncertain.active is False


def test_interpret_creative_intent_is_semantic_and_provider_neutral(monkeypatch) -> None:
    async def fake_request(config, prompt, *, system_prompt, max_tokens, model):
        assert "mood, energy, activity, occasion" in system_prompt
        assert "genre, artist or era" in system_prompt
        return json.dumps(
            {
                "requirements": ["celebratory social atmosphere"],
                "confidence": 0.94,
            }
        )

    monkeypatch.setattr(creative_intent, "request_structured_json", fake_request)

    intent = asyncio.run(
        interpret_creative_intent(_config(), "richiesta musicale in una lingua qualsiasi")
    )

    assert intent.active is True
    assert intent.requirements == ("celebratory social atmosphere",)


def test_creative_fit_rejects_high_confidence_conflicts_and_weak_fit(monkeypatch) -> None:
    async def fake_request(config, prompt, *, system_prompt, max_tokens, model):
        payload = json.loads(prompt)
        assert payload["creative_requirements"] == ["energetic social setting"]
        assert len(payload["tracks"]) == 5
        assert set(payload["tracks"][0]) == {"index", "artist", "title"}
        assert "Generated description" not in prompt
        assert "Generated reason" not in prompt
        assert "positively contribute" in system_prompt
        assert "self-justifying evidence" in system_prompt
        assert 'verdict="weak_fit"' in system_prompt
        return json.dumps(
            {
                "assessments": [
                    {
                        "index": 1,
                        "verdict": "conflict",
                        "confidence": 0.97,
                        "reason": "Clearly too subdued for the requested setting.",
                    },
                    {
                        "index": 2,
                        "verdict": "weak_fit",
                        "confidence": 0.94,
                        "reason": "Recognizable song, but only marginally supports the requested setting.",
                    },
                    {
                        "index": 3,
                        "verdict": "weak_fit",
                        "confidence": 0.7,
                        "reason": "Possible mismatch, but uncertain.",
                    },
                    {
                        "index": 4,
                        "verdict": "unknown",
                        "confidence": 0.99,
                        "reason": "Insufficient certainty about the song.",
                    },
                    {
                        "index": 5,
                        "verdict": "fit",
                        "confidence": 0.98,
                        "reason": "Clearly supports the requested setting.",
                    },
                ]
            }
        )

    monkeypatch.setattr(creative_intent, "request_structured_json", fake_request)
    token = activate_creative_intent(
        CreativeIntent(("energetic social setting",), confidence=0.95)
    )
    try:
        conflicts = asyncio.run(
            assess_creative_fit(
                _config(),
                [
                    _track("Track 1"),
                    _track("Track 2"),
                    _track("Track 3"),
                    _track("Track 4"),
                    _track("Track 5"),
                ],
            )
        )
    finally:
        reset_creative_intent(token)

    assert [item.index for item in conflicts] == [1, 2]
    assert [item.confidence for item in conflicts] == [0.97, 0.94]


def test_unknown_creative_fit_never_becomes_rejection(monkeypatch) -> None:
    async def fake_request(config, prompt, *, system_prompt, max_tokens, model):
        return json.dumps(
            {
                "assessments": [
                    {
                        "index": 1,
                        "verdict": "unknown",
                        "confidence": 1.0,
                        "reason": "The evaluator does not know the song well enough.",
                    }
                ]
            }
        )

    monkeypatch.setattr(creative_intent, "request_structured_json", fake_request)
    token = activate_creative_intent(
        CreativeIntent(("focused low-distraction atmosphere",), confidence=0.95)
    )
    try:
        conflicts = asyncio.run(assess_creative_fit(_config(), [_track("Obscure Track")]))
    finally:
        reset_creative_intent(token)

    assert conflicts == []


def test_creative_fit_is_noop_without_explicit_intent(monkeypatch) -> None:
    called = False

    async def fake_request(*args, **kwargs):
        nonlocal called
        called = True
        return "{}"

    monkeypatch.setattr(creative_intent, "request_structured_json", fake_request)
    token = activate_creative_intent(CreativeIntent())
    try:
        conflicts = asyncio.run(assess_creative_fit(_config(), [_track("Track")]))
    finally:
        reset_creative_intent(token)

    assert conflicts == []
    assert called is False


def test_creative_repair_prompt_preserves_hard_constraints_and_replaces_conflicts() -> None:
    intent = CreativeIntent(("focused low-distraction atmosphere",), confidence=0.95)
    draft = {
        "tracks": [
            _track("Distracting Track"),
            _track("Suitable Track"),
        ]
    }
    conflicts = [
        creative_intent.CreativeConflict(
            index=1,
            confidence=0.96,
            reason="Only marginally supports the requested atmosphere.",
        )
    ]

    prompt = creative_repair_prompt(
        "Original request with an explicit date range",
        2,
        draft,
        conflicts,
        intent=intent,
    )

    assert "Preserve every explicit factual constraint" in prompt
    assert "Do not relax dates" in prompt
    assert "focused low-distraction atmosphere" in prompt
    assert "Distracting Track" in prompt
    assert "must be replaced" in prompt
    assert "positively supports" in prompt
