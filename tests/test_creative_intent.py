from __future__ import annotations

import asyncio
import json

import pytest

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
from backend.lastfm_tags import LastfmTagEvidence
from backend.reccobeats_features import ReccoBeatsAudioEvidence


def _config() -> AppConfig:
    return AppConfig(provider="openai", api_key="sk-test", model="test-model")


def _track(title: str) -> dict[str, str]:
    return {
        "artist": "Test Artist",
        "title": title,
        "description": "Generated description claiming perfect suitability.",
        "reason": "Generated reason claiming this is ideal for the requested mood.",
    }


async def _empty_tag_evidence(tracks):
    return [LastfmTagEvidence() for _ in tracks]


async def _empty_audio_evidence(tracks):
    return [ReccoBeatsAudioEvidence() for _ in tracks]


@pytest.fixture(autouse=True)
def _disable_live_reccobeats(monkeypatch) -> None:
    monkeypatch.setattr(
        creative_intent,
        "audio_evidence_for_tracks",
        _empty_audio_evidence,
    )


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


def test_creative_fit_uses_external_evidence_without_self_justification(monkeypatch) -> None:
    async def fake_tags(tracks):
        return [
            LastfmTagEvidence(track_tags=("dance", "party")),
            LastfmTagEvidence(artist_tags=("pop", "electropop")),
            LastfmTagEvidence(),
            LastfmTagEvidence(),
            LastfmTagEvidence(),
        ]

    async def fake_audio(tracks):
        return [
            ReccoBeatsAudioEvidence(
                match_source="track_search",
                danceability=0.86,
                energy=0.82,
                valence=0.77,
                tempo=124.0,
                liveness=0.61,
            ),
            ReccoBeatsAudioEvidence(),
            ReccoBeatsAudioEvidence(),
            ReccoBeatsAudioEvidence(),
            ReccoBeatsAudioEvidence(),
        ]

    async def fake_request(config, prompt, *, system_prompt, max_tokens, model):
        payload = json.loads(prompt)
        assert payload["creative_requirements"] == ["energetic social setting"]
        assert len(payload["tracks"]) == 5
        assert set(payload["tracks"][0]) == {
            "index",
            "artist",
            "title",
            "reccobeats_audio_features",
            "reccobeats_match_source",
            "lastfm_track_tags",
            "lastfm_artist_tags",
        }
        assert payload["tracks"][0]["reccobeats_audio_features"] == {
            "danceability": 0.86,
            "energy": 0.82,
            "valence": 0.77,
            "tempo": 124.0,
            "liveness": 0.61,
        }
        assert payload["tracks"][0]["reccobeats_match_source"] == "track_search"
        assert payload["tracks"][0]["lastfm_track_tags"] == ["dance", "party"]
        assert payload["tracks"][0]["lastfm_artist_tags"] == []
        assert payload["tracks"][1]["reccobeats_audio_features"] == {}
        assert payload["tracks"][1]["lastfm_track_tags"] == []
        assert payload["tracks"][1]["lastfm_artist_tags"] == ["pop", "electropop"]
        assert "Generated description" not in prompt
        assert "Generated reason" not in prompt
        assert "positively contribute" in system_prompt
        assert "self-justifying evidence" in system_prompt
        assert "quantitative external evidence" in system_prompt
        assert "single fixed danceability" in system_prompt
        assert "must never be treated as proof" in system_prompt
        assert "community-generated external evidence" in system_prompt
        assert "stronger evidence than generic artist tags" in system_prompt
        assert 'verdict="weak_fit"' in system_prompt
        return json.dumps(
            {
                "assessments": [
                    {
                        "index": 1,
                        "verdict": "fit",
                        "confidence": 0.98,
                        "reason": "External evidence supports the requested setting.",
                    },
                    {
                        "index": 2,
                        "verdict": "weak_fit",
                        "confidence": 0.94,
                        "reason": "Only broad artist-level evidence supports the setting.",
                    },
                    {
                        "index": 3,
                        "verdict": "conflict",
                        "confidence": 0.97,
                        "reason": "Clearly too subdued for the requested setting.",
                    },
                    {
                        "index": 4,
                        "verdict": "unknown",
                        "confidence": 0.99,
                        "reason": "Insufficient certainty about the song.",
                    },
                    {
                        "index": 5,
                        "verdict": "weak_fit",
                        "confidence": 0.7,
                        "reason": "Possible mismatch, but uncertain.",
                    },
                ]
            }
        )

    monkeypatch.setattr(creative_intent, "tag_evidence_for_tracks", fake_tags)
    monkeypatch.setattr(creative_intent, "audio_evidence_for_tracks", fake_audio)
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

    assert [item.index for item in conflicts] == [2, 3]
    assert [item.confidence for item in conflicts] == [0.94, 0.97]


def test_conflict_and_weak_fit_use_distinct_calibrated_thresholds(monkeypatch) -> None:
    async def fake_request(config, prompt, *, system_prompt, max_tokens, model):
        return json.dumps(
            {
                "assessments": [
                    {
                        "index": 1,
                        "verdict": "conflict",
                        "confidence": 0.75,
                        "reason": "Credible contradiction.",
                    },
                    {
                        "index": 2,
                        "verdict": "conflict",
                        "confidence": 0.74,
                        "reason": "Too uncertain.",
                    },
                    {
                        "index": 3,
                        "verdict": "weak_fit",
                        "confidence": 0.80,
                        "reason": "Credibly marginal fit.",
                    },
                    {
                        "index": 4,
                        "verdict": "weak_fit",
                        "confidence": 0.79,
                        "reason": "Still uncertain.",
                    },
                    {
                        "index": 5,
                        "verdict": "unknown",
                        "confidence": 1.0,
                        "reason": "Unknown must never reject.",
                    },
                ]
            }
        )

    monkeypatch.setattr(creative_intent, "tag_evidence_for_tracks", _empty_tag_evidence)
    monkeypatch.setattr(creative_intent, "request_structured_json", fake_request)

    conflicts = asyncio.run(
        assess_creative_fit(
            _config(),
            [_track(f"Track {index}") for index in range(1, 6)],
            intent=CreativeIntent(("festive party atmosphere",), confidence=0.95),
        )
    )

    assert [item.index for item in conflicts] == [1, 3]


def test_full_evaluation_failure_retries_in_smaller_batches(monkeypatch) -> None:
    calls: list[int] = []

    async def fake_request(config, prompt, *, system_prompt, max_tokens, model):
        payload = json.loads(prompt)
        count = len(payload["tracks"])
        calls.append(count)
        if count > creative_intent.EVALUATION_BATCH_SIZE:
            raise RuntimeError("full response unavailable")
        if count == creative_intent.EVALUATION_BATCH_SIZE:
            return json.dumps(
                {
                    "assessments": [
                        {
                            "index": 1,
                            "verdict": "conflict",
                            "confidence": 0.80,
                            "reason": "First batch conflict.",
                        }
                    ]
                }
            )
        return json.dumps(
            {
                "assessments": [
                    {
                        "index": 1,
                        "verdict": "weak_fit",
                        "confidence": 0.80,
                        "reason": "Final batch weak fit.",
                    }
                ]
            }
        )

    monkeypatch.setattr(creative_intent, "tag_evidence_for_tracks", _empty_tag_evidence)
    monkeypatch.setattr(creative_intent, "request_structured_json", fake_request)

    tracks = [_track(f"Track {index}") for index in range(1, 10)]
    conflicts = asyncio.run(
        assess_creative_fit(
            _config(),
            tracks,
            intent=CreativeIntent(("festive party atmosphere",), confidence=0.95),
        )
    )

    assert calls == [9, 8, 1]
    assert [item.index for item in conflicts] == [1, 9]


def test_lastfm_tag_failure_fails_open_to_other_available_evidence(monkeypatch) -> None:
    async def broken_tags(tracks):
        raise RuntimeError("Last.fm unavailable")

    async def fake_audio(tracks):
        return [
            ReccoBeatsAudioEvidence(
                match_source="track_search",
                energy=0.8,
                danceability=0.75,
            )
            for _ in tracks
        ]

    async def fake_request(config, prompt, *, system_prompt, max_tokens, model):
        payload = json.loads(prompt)
        assert payload["tracks"][0]["lastfm_track_tags"] == []
        assert payload["tracks"][0]["lastfm_artist_tags"] == []
        assert payload["tracks"][0]["reccobeats_audio_features"] == {
            "danceability": 0.75,
            "energy": 0.8,
        }
        return json.dumps(
            {
                "assessments": [
                    {
                        "index": 1,
                        "verdict": "fit",
                        "confidence": 0.95,
                        "reason": "Known suitable recording.",
                    }
                ]
            }
        )

    monkeypatch.setattr(creative_intent, "tag_evidence_for_tracks", broken_tags)
    monkeypatch.setattr(creative_intent, "audio_evidence_for_tracks", fake_audio)
    monkeypatch.setattr(creative_intent, "request_structured_json", fake_request)

    conflicts = asyncio.run(
        assess_creative_fit(
            _config(),
            [_track("Track")],
            intent=CreativeIntent(("energetic social setting",), confidence=0.95),
        )
    )

    assert conflicts == []


def test_reccobeats_failure_fails_open_to_identity_and_tags(monkeypatch) -> None:
    async def broken_audio(tracks):
        raise RuntimeError("ReccoBeats unavailable")

    async def fake_request(config, prompt, *, system_prompt, max_tokens, model):
        payload = json.loads(prompt)
        assert payload["tracks"][0]["reccobeats_audio_features"] == {}
        assert payload["tracks"][0]["reccobeats_match_source"] == ""
        return json.dumps(
            {
                "assessments": [
                    {
                        "index": 1,
                        "verdict": "fit",
                        "confidence": 0.95,
                        "reason": "Known suitable recording.",
                    }
                ]
            }
        )

    monkeypatch.setattr(creative_intent, "tag_evidence_for_tracks", _empty_tag_evidence)
    monkeypatch.setattr(creative_intent, "audio_evidence_for_tracks", broken_audio)
    monkeypatch.setattr(creative_intent, "request_structured_json", fake_request)

    conflicts = asyncio.run(
        assess_creative_fit(
            _config(),
            [_track("Track")],
            intent=CreativeIntent(("energetic social setting",), confidence=0.95),
        )
    )

    assert conflicts == []


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

    monkeypatch.setattr(creative_intent, "tag_evidence_for_tracks", _empty_tag_evidence)
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

    async def fake_tags(*args, **kwargs):
        nonlocal called
        called = True
        return []

    async def fake_audio(*args, **kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(creative_intent, "tag_evidence_for_tracks", fake_tags)
    monkeypatch.setattr(creative_intent, "audio_evidence_for_tracks", fake_audio)
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
