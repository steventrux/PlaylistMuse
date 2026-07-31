from __future__ import annotations

import asyncio
import json
from pathlib import Path

import backend.config as config
from backend.config import AppConfig, load_config, save_config
from backend.youtube_routes import AIProviderActivation, activate_ai_provider


def _set_config_path(monkeypatch, tmp_path: Path) -> Path:
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    return path


def test_load_config_migrates_legacy_active_profile(monkeypatch, tmp_path: Path) -> None:
    path = _set_config_path(monkeypatch, tmp_path)
    path.write_text(
        json.dumps(
            {
                "provider": "gemini",
                "model": "gemini-test",
                "fallback_1": "gemini-fallback",
                "fallback_2": "",
                "base_url": "",
                "api_keys": {"gemini": "AIza-test-key"},
            }
        ),
        encoding="utf-8",
    )

    loaded = load_config()

    assert loaded.provider == "gemini"
    assert loaded.configured is True
    assert loaded.profile_for("gemini")["model"] == "gemini-test"
    assert loaded.profile_for("gemini")["fallback_1"] == "gemini-fallback"


def test_save_config_preserves_multiple_provider_profiles(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_config_path(monkeypatch, tmp_path)

    gemini = AppConfig(
        provider="gemini",
        api_key="AIza-gemini-key",
        model="gemini-test",
        provider_api_keys={"gemini": "AIza-gemini-key"},
    )
    save_config(gemini)

    current = load_config()
    openai = AppConfig(
        provider="openai",
        api_key="sk-openai-key",
        model="gpt-test",
        fallback_1="gpt-fallback",
        provider_api_keys={
            **current.provider_api_keys,
            "openai": "sk-openai-key",
        },
        provider_profiles=current.provider_profiles,
    )
    save_config(openai)

    loaded = load_config()

    assert loaded.provider == "openai"
    assert loaded.profile_for("openai")["model"] == "gpt-test"
    assert loaded.profile_for("gemini")["model"] == "gemini-test"
    assert loaded.configuration_for("openai").configured is True
    assert loaded.configuration_for("gemini").configured is True


def test_activate_ai_provider_switches_to_saved_profile(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_config_path(monkeypatch, tmp_path)

    profiles = {
        "gemini": {
            "model": "gemini-test",
            "fallback_1": "",
            "fallback_2": "",
            "base_url": "",
        },
        "openai": {
            "model": "gpt-test",
            "fallback_1": "",
            "fallback_2": "",
            "base_url": "",
        },
    }
    save_config(
        AppConfig(
            provider="openai",
            api_key="sk-openai-key",
            model="gpt-test",
            provider_api_keys={
                "openai": "sk-openai-key",
                "gemini": "AIza-gemini-key",
            },
            provider_profiles=profiles,
        )
    )

    response = asyncio.run(
        activate_ai_provider(AIProviderActivation(provider="gemini"))
    )
    loaded = load_config()

    assert response["active_provider"] == "gemini"
    assert response["profiles"]["openai"]["configured"] is True
    assert response["profiles"]["gemini"]["active"] is True
    assert loaded.provider == "gemini"
    assert loaded.model == "gemini-test"
