import asyncio
import json

from backend.config import AppConfig
from backend.prompt_analysis import analyze_prompt_semantics, parse_analysis
from backend.provider_rate_limits import ProviderRateLimitedError


def test_prompt_analysis_accepts_language_independent_semantic_categories() -> None:
    result = parse_analysis(
        json.dumps(
            {
                "dimensions": ["genre", "period", "genre", "unknown"],
                "hard_constraints": 4,
                "soft_constraints": 1,
                "structures": ["progression", "alternation", "unsupported"],
                "relations": 2,
                "ambiguities": ["主観的な条件を定義してください"],
                "conflicts": ["Les deux contraintes sont incompatibles"],
                "missing_information": [],
                "imprecisions": [],
                "possible_typos": ["Möglicher Tippfehler im Künstlernamen"],
                "required_recording_types": ["live"],
                "included_recording_types": [],
                "excluded_recording_types": [],
                "recording_type_confidence": 0.97,
            },
            ensure_ascii=False,
        )
    )

    assert result["dimensions"] == ["genre", "period"]
    assert result["structures"] == ["progression", "alternation"]
    assert result["hard_constraints"] == 4
    assert result["ambiguities"] == ["主観的な条件を定義してください"]
    assert result["conflicts"] == ["Les deux contraintes sont incompatibles"]
    assert result["possible_typos"] == ["Möglicher Tippfehler im Künstlernamen"]
    assert result["required_recording_types"] == ["live"]
    assert result["recording_type_confidence"] == 0.97


def test_prompt_analysis_clamps_counts_and_discards_invalid_shapes() -> None:
    result = parse_analysis(
        json.dumps(
            {
                "dimensions": "genre",
                "hard_constraints": 999,
                "soft_constraints": -2,
                "structures": None,
                "relations": "not-a-number",
                "ambiguities": "subjective",
            }
        )
    )

    assert result["dimensions"] == []
    assert result["hard_constraints"] == 20
    assert result["soft_constraints"] == 0
    assert result["structures"] == []
    assert result["relations"] == 0
    assert result["ambiguities"] == []
    assert result["required_recording_types"] == []
    assert result["recording_type_confidence"] == 0.0


def test_prompt_analysis_adds_structured_filter_conflict(monkeypatch) -> None:
    async def fake_request(*args, **kwargs):
        return json.dumps(
            {
                "dimensions": ["genre"],
                "hard_constraints": 1,
                "soft_constraints": 0,
                "structures": [],
                "relations": 0,
                "ambiguities": [],
                "conflicts": [],
                "missing_information": [],
                "imprecisions": [],
                "possible_typos": [],
                "required_recording_types": ["live"],
                "included_recording_types": [],
                "excluded_recording_types": [],
                "recording_type_confidence": 0.99,
            }
        )

    monkeypatch.setattr("backend.prompt_analysis.request_structured_json", fake_request)
    config = AppConfig(
        provider="openai",
        api_key="sk-test",
        model="test-model",
    )

    result = asyncio.run(
        analyze_prompt_semantics(
            config,
            "create a rock playlist with only live versions",
            track_count=20,
            options={
                "exclude_live": True,
                "exclude_covers": True,
                "exclude_remixes": True,
            },
        )
    )

    assert any(
        conflict.startswith("FILTER_CONFLICT::exclude_live::")
        for conflict in result["conflicts"]
    )


def test_rate_limited_model_falls_back_to_next_model_instead_of_aborting(monkeypatch) -> None:
    """A cached rate-limit on one model must not abort the whole fallback loop.

    Regression test: ProviderRateLimitedError used to propagate uncaught out of the
    model_order loop, so a rate-limited primary model failed the whole request instead
    of trying the next configured model.
    """

    async def fake_request(config, prompt, *, system_prompt, max_tokens, model=None):
        if model == "primary-model":
            raise ProviderRateLimitedError("openai/primary-model is cached as rate-limited")
        assert model == "fallback-model"
        return json.dumps(
            {
                "dimensions": ["genre"],
                "hard_constraints": 1,
                "soft_constraints": 0,
                "structures": [],
                "relations": 0,
                "ambiguities": [],
                "conflicts": [],
                "missing_information": [],
                "imprecisions": [],
                "possible_typos": [],
                "required_recording_types": [],
                "included_recording_types": [],
                "excluded_recording_types": [],
                "recording_type_confidence": 0.5,
            }
        )

    monkeypatch.setattr("backend.prompt_analysis.request_structured_json", fake_request)
    config = AppConfig(
        provider="openai",
        api_key="sk-test",
        model="primary-model",
        fallback_1="fallback-model",
    )

    result = asyncio.run(
        analyze_prompt_semantics(
            config,
            "create a rock playlist",
            track_count=20,
            options={"exclude_live": False, "exclude_covers": False, "exclude_remixes": False},
        )
    )

    assert result["dimensions"] == ["genre"]
