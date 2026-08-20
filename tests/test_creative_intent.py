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
    interpret_style_request,
    merge_creative_intents,
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


def test_interpret_style_request_captures_an_explicit_genre(monkeypatch) -> None:
    async def fake_request(config, prompt, *, system_prompt, max_tokens, model):
        assert "genre or style" in system_prompt
        return json.dumps({"requirements": ["house"], "confidence": 0.9})

    monkeypatch.setattr(creative_intent, "request_structured_json", fake_request)

    intent = asyncio.run(interpret_style_request(_config(), "playlist house con i miei artisti"))

    assert intent.requirements == ("house",)
    assert intent.confidence == 0.9


def test_merge_creative_intents_combines_and_dedupes() -> None:
    base = CreativeIntent(("chill vibe",), 0.85)
    extra = CreativeIntent(("house", "chill vibe"), 0.9)

    merged = merge_creative_intents(base, extra)

    assert merged.requirements == ("chill vibe", "house")
    assert merged.confidence == 0.85  # min of both, since base already had a requirement


def test_merge_creative_intents_adopts_extra_confidence_when_base_is_empty() -> None:
    merged = merge_creative_intents(CreativeIntent(), CreativeIntent(("house",), 0.9))

    assert merged.requirements == ("house",)
    assert merged.confidence == 0.9


def test_merge_creative_intents_is_a_noop_when_extra_has_no_requirements() -> None:
    base = CreativeIntent(("chill vibe",), 0.85)

    assert merge_creative_intents(base, CreativeIntent()) is base


def test_creative_fit_refines_only_uncertain_tracks_with_audio_evidence(monkeypatch) -> None:
    calls = 0

    async def fake_tags(tracks):
        return [
            LastfmTagEvidence(track_tags=("dance", "party")),
            LastfmTagEvidence(),
            LastfmTagEvidence(),
            LastfmTagEvidence(),
            LastfmTagEvidence(),
        ]

    async def fake_audio(tracks):
        assert [track["title"] for track in tracks] == [
            "Track 4",
            "Track 5",
        ]
        return [
            ReccoBeatsAudioEvidence(
                match_source="track_search",
                energy=0.52,
                valence=0.44,
            ),
            ReccoBeatsAudioEvidence(
                match_source="artist_catalog",
                danceability=0.72,
                energy=0.74,
            ),
        ]

    async def fake_request(config, prompt, *, system_prompt, max_tokens, model):
        nonlocal calls
        calls += 1
        payload = json.loads(prompt)
        assert "Generated description" not in prompt
        assert "Generated reason" not in prompt
        assert "quantitative external evidence" in system_prompt
        assert "single fixed danceability" in system_prompt
        assert "must never be treated as proof" in system_prompt
        assert "Audio features describe acoustic character" in system_prompt
        assert "track-specific tags" in system_prompt

        if calls == 1:
            assert payload["creative_requirements"] == ["energetic social setting"]
            assert len(payload["tracks"]) == 5
            assert all(
                track["reccobeats_audio_features"] == {}
                for track in payload["tracks"]
            )
            assert payload["tracks"][0]["lastfm_track_tags"] == ["dance", "party"]
            assert "lastfm_artist_tags" not in payload["tracks"][0]
            assert "lastfm_artist_tags" not in payload["tracks"][1]
            return json.dumps(
                {
                    "assessments": [
                        {
                            "index": 1,
                            "verdict": "fit",
                            "confidence": 0.98,
                            "reason": "Strong fit.",
                        },
                        {
                            "index": 2,
                            "verdict": "weak_fit",
                            "confidence": 0.79,
                            "reason": "Borderline marginal fit.",
                        },
                        {
                            "index": 3,
                            "verdict": "conflict",
                            "confidence": 0.97,
                            "reason": "Clear contradiction.",
                        },
                        {
                            "index": 4,
                            "verdict": "unknown",
                            "confidence": 0.99,
                            "reason": "Insufficient evidence.",
                        },
                        {
                            "index": 5,
                            "verdict": "fit",
                            "confidence": 0.70,
                            "reason": "Plausible but uncertain fit.",
                        },
                    ]
                }
            )

        assert calls == 2
        assert [track["title"] for track in payload["tracks"]] == [
            "Track 4",
            "Track 5",
        ]
        assert payload["tracks"][0]["reccobeats_audio_features"] == {
            "energy": 0.52,
            "valence": 0.44,
        }
        assert payload["tracks"][0]["reccobeats_match_source"] == "track_search"
        assert payload["tracks"][1]["reccobeats_match_source"] == "artist_catalog"
        return json.dumps(
            {
                "assessments": [
                    {
                        "index": 1,
                        "verdict": "fit",
                        "confidence": 0.90,
                        "reason": "Audio evidence supports a role in the setting.",
                    },
                    {
                        "index": 2,
                        "verdict": "fit",
                        "confidence": 0.88,
                        "reason": "Audio evidence supports the setting.",
                    },
                ]
            }
        )

    monkeypatch.setattr(creative_intent, "tag_evidence_for_tracks", fake_tags)
    monkeypatch.setattr(creative_intent, "audio_evidence_for_tracks", fake_audio)
    monkeypatch.setattr(creative_intent, "request_structured_json", fake_request)

    conflicts = asyncio.run(
        assess_creative_fit(
            _config(),
            [_track(f"Track {index}") for index in range(1, 6)],
            intent=CreativeIntent(("energetic social setting",), confidence=0.95),
        )
    )

    assert calls == 2
    assert [item.index for item in conflicts] == [2, 3]
    assert [item.confidence for item in conflicts] == [0.79, 0.97]


def test_semantic_weak_fit_is_not_reopened_by_audio_features(monkeypatch) -> None:
    audio_called = False

    async def fake_audio(tracks):
        nonlocal audio_called
        audio_called = True
        return [
            ReccoBeatsAudioEvidence(
                match_source="track_search",
                danceability=0.90,
                energy=0.95,
                valence=0.95,
                tempo=128.0,
            )
            for _ in tracks
        ]

    async def fake_request(config, prompt, *, system_prompt, max_tokens, model):
        return json.dumps(
            {
                "assessments": [
                    {
                        "index": 1,
                        "verdict": "weak_fit",
                        "confidence": 0.60,
                        "reason": "The song is emotionally reflective rather than celebratory.",
                    }
                ]
            }
        )

    monkeypatch.setattr(creative_intent, "tag_evidence_for_tracks", _empty_tag_evidence)
    monkeypatch.setattr(creative_intent, "audio_evidence_for_tracks", fake_audio)
    monkeypatch.setattr(creative_intent, "request_structured_json", fake_request)

    conflicts = asyncio.run(
        assess_creative_fit(
            _config(),
            [_track("Semantically weak party fit")],
            intent=CreativeIntent(("festive party atmosphere",), confidence=0.95),
        )
    )

    assert [item.index for item in conflicts] == [1]
    assert conflicts[0].confidence == 0.60
    assert audio_called is False


def test_successful_fallback_model_is_reused_for_audio_refinement(monkeypatch) -> None:
    calls: list[str] = []
    config = AppConfig(
        provider="openai",
        api_key="sk-test",
        model="primary-model",
        fallback_1="fallback-one",
        fallback_2="fallback-two",
    )

    async def fake_audio(tracks):
        return [
            ReccoBeatsAudioEvidence(
                match_source="track_search",
                danceability=0.82,
                energy=0.86,
                valence=0.74,
            )
        ]

    async def fake_request(config, prompt, *, system_prompt, max_tokens, model):
        calls.append(model)
        payload = json.loads(prompt)
        has_audio = bool(payload["tracks"][0]["reccobeats_audio_features"])
        if model in {"primary-model", "fallback-one"}:
            raise json.JSONDecodeError("invalid structured output", "x", 0)
        if not has_audio:
            return json.dumps(
                {
                    "assessments": [
                        {
                            "index": 1,
                            "verdict": "unknown",
                            "confidence": 0.90,
                            "reason": "Needs external evidence.",
                        }
                    ]
                }
            )
        return json.dumps(
            {
                "assessments": [
                    {
                        "index": 1,
                        "verdict": "fit",
                        "confidence": 0.95,
                        "reason": "Audio evidence supports the requested experience.",
                    }
                ]
            }
        )

    monkeypatch.setattr(creative_intent, "tag_evidence_for_tracks", _empty_tag_evidence)
    monkeypatch.setattr(creative_intent, "audio_evidence_for_tracks", fake_audio)
    monkeypatch.setattr(creative_intent, "request_structured_json", fake_request)

    conflicts = asyncio.run(
        assess_creative_fit(
            config,
            [_track("Track")],
            intent=CreativeIntent(("festive party atmosphere",), confidence=0.95),
        )
    )

    assert conflicts == []
    assert calls == [
        "primary-model",
        "fallback-one",
        "fallback-two",
        "fallback-two",
    ]


def test_audio_refinement_is_bounded_and_uses_only_unresolved_or_uncertain_positive_decisions() -> None:
    diagnostics = [
        {"index": 1, "verdict": "fit", "confidence": 0.95},
        {"index": 2, "verdict": "weak_fit", "confidence": 0.79},
        {"index": 3, "verdict": "conflict", "confidence": 0.74},
        {"index": 4, "verdict": "unknown", "confidence": 0.99},
        {"index": 5, "verdict": "unknown", "confidence": 0.80},
        {"index": 6, "verdict": "fit", "confidence": 0.60},
        {"index": 7, "verdict": "fit", "confidence": 0.70},
        {"index": 8, "verdict": "weak_fit", "confidence": 0.78},
        {"index": 9, "verdict": "unknown", "confidence": 0.70},
    ]
    conflicts = [
        creative_intent.CreativeConflict(
            index=3,
            confidence=0.90,
            reason="already rejected",
        )
    ]

    selected = creative_intent._audio_refinement_indexes(diagnostics, conflicts)

    assert selected == [4, 5, 9, 6, 7]
    assert 2 not in selected
    assert 8 not in selected
    assert len(selected) <= creative_intent.MAX_AUDIO_REFINEMENT_TRACKS


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
                        "confidence": 0.60,
                        "reason": "Credibly marginal fit.",
                    },
                    {
                        "index": 4,
                        "verdict": "weak_fit",
                        "confidence": 0.59,
                        "reason": "Still too uncertain.",
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


def test_lastfm_failure_can_still_use_targeted_audio_refinement(monkeypatch) -> None:
    calls = 0

    async def broken_tags(tracks):
        raise RuntimeError("Last.fm unavailable")

    async def fake_audio(tracks):
        assert [track["title"] for track in tracks] == ["Track"]
        return [
            ReccoBeatsAudioEvidence(
                match_source="track_search",
                energy=0.8,
                danceability=0.75,
            )
        ]

    async def fake_request(config, prompt, *, system_prompt, max_tokens, model):
        nonlocal calls
        calls += 1
        payload = json.loads(prompt)
        assert payload["tracks"][0]["lastfm_track_tags"] == []
        assert "lastfm_artist_tags" not in payload["tracks"][0]
        if calls == 1:
            assert payload["tracks"][0]["reccobeats_audio_features"] == {}
            return json.dumps(
                {
                    "assessments": [
                        {
                            "index": 1,
                            "verdict": "unknown",
                            "confidence": 0.95,
                            "reason": "Need more evidence.",
                        }
                    ]
                }
            )
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
                        "reason": "External audio evidence supports the fit.",
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
    assert calls == 2


def test_reccobeats_failure_preserves_first_pass_unknown_as_non_rejection(monkeypatch) -> None:
    calls = 0

    async def broken_audio(tracks):
        raise RuntimeError("ReccoBeats unavailable")

    async def fake_request(config, prompt, *, system_prompt, max_tokens, model):
        nonlocal calls
        calls += 1
        return json.dumps(
            {
                "assessments": [
                    {
                        "index": 1,
                        "verdict": "unknown",
                        "confidence": 1.0,
                        "reason": "Insufficient certainty.",
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
    assert calls == 1


def test_clear_first_pass_fit_skips_reccobeats(monkeypatch) -> None:
    audio_called = False

    async def fake_audio(tracks):
        nonlocal audio_called
        audio_called = True
        return [ReccoBeatsAudioEvidence() for _ in tracks]

    async def fake_request(config, prompt, *, system_prompt, max_tokens, model):
        return json.dumps(
            {
                "assessments": [
                    {
                        "index": 1,
                        "verdict": "fit",
                        "confidence": 0.95,
                        "reason": "Clear fit.",
                    }
                ]
            }
        )

    monkeypatch.setattr(creative_intent, "tag_evidence_for_tracks", _empty_tag_evidence)
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
    assert audio_called is False


def test_unknown_creative_fit_never_becomes_rejection_without_audio(monkeypatch) -> None:
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

    conflicts = asyncio.run(
        assess_creative_fit(
            _config(),
            [_track("Obscure Track")],
            intent=CreativeIntent(("focused low-distraction atmosphere",), confidence=0.95),
        )
    )

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
