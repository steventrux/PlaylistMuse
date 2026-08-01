from __future__ import annotations

import asyncio
import json
from pathlib import Path

import backend.config as config
from backend.config import (
    AppConfig,
    activate_provider,
    disconnect_provider,
    load_config,
    save_config,
)
from backend.youtube_routes import AIProviderActivation, activate_ai_provider

ENV_NAMES = (
    "PLAYLISTMUSE_AI_PROVIDER",
    "PLAYLISTMUSE_AI_API_KEY",
    "PLAYLISTMUSE_AI_MODEL",
    "PLAYLISTMUSE_AI_FALLBACK_1",
    "PLAYLISTMUSE_AI_FALLBACK_2",
    "PLAYLISTMUSE_AI_BASE_URL",
)


def _set_config_path(monkeypatch, tmp_path: Path) -> Path:
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
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


def test_save_config_preserves_active_provider_and_multiple_profiles(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_config_path(monkeypatch, tmp_path)

    save_config(
        AppConfig(
            provider="gemini",
            api_key="AIza-gemini-key",
            model="gemini-test",
            provider_api_keys={"gemini": "AIza-gemini-key"},
        )
    )

    current = load_config()
    save_config(
        AppConfig(
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
    )

    loaded = load_config()

    assert loaded.provider == "gemini"
    assert loaded.profile_for("openai")["model"] == "gpt-test"
    assert loaded.profile_for("gemini")["model"] == "gemini-test"
    assert loaded.configuration_for("openai").configured is True
    assert loaded.configuration_for("gemini").configured is True


def test_incomplete_profile_does_not_replace_working_provider(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_config_path(monkeypatch, tmp_path)
    save_config(
        AppConfig(
            provider="gemini",
            api_key="AIza-gemini-key",
            model="gemini-test",
            provider_api_keys={"gemini": "AIza-gemini-key"},
        )
    )

    current = load_config()
    save_config(
        AppConfig(
            provider="anthropic",
            api_key="",
            model="claude-test",
            provider_api_keys=current.provider_api_keys,
            provider_profiles=current.provider_profiles,
        )
    )

    loaded = load_config()

    assert loaded.provider == "gemini"
    assert loaded.configured is True
    assert loaded.profile_for("anthropic")["model"] == "claude-test"
    assert loaded.configuration_for("anthropic").configured is False


def test_openrouter_key_configures_auto_and_free(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_config_path(monkeypatch, tmp_path)
    save_config(
        AppConfig(
            provider="openrouter_free",
            api_key="sk-or-openrouter-key",
            model="openrouter/free",
            provider_api_keys={"openrouter": "sk-or-openrouter-key"},
        )
    )

    loaded = load_config()

    assert loaded.key_is_saved("openrouter_auto") is True
    assert loaded.key_is_saved("openrouter_free") is True
    assert loaded.profile_for("openrouter_auto")["model"] == "openrouter/auto"
    assert loaded.profile_for("openrouter_free")["model"] == "openrouter/free"
    assert loaded.is_provider_configured("openrouter_auto") is True
    assert loaded.is_provider_configured("openrouter_free") is True


def test_activate_ai_provider_switches_despite_environment_default(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _set_config_path(monkeypatch, tmp_path)
    save_config(
        AppConfig(
            provider="gemini",
            api_key="AIza-gemini-key",
            model="gemini-test",
            provider_api_keys={"gemini": "AIza-gemini-key"},
        )
    )
    current = load_config()
    save_config(
        AppConfig(
            provider="openrouter_free",
            api_key="sk-or-openrouter-key",
            model="openrouter/free",
            provider_api_keys={
                **current.provider_api_keys,
                "openrouter": "sk-or-openrouter-key",
            },
            provider_profiles=current.provider_profiles,
        )
    )

    monkeypatch.setenv("PLAYLISTMUSE_AI_PROVIDER", "gemini")
    monkeypatch.setenv("PLAYLISTMUSE_AI_API_KEY", "AIza-environment-key")
    monkeypatch.setenv("PLAYLISTMUSE_AI_MODEL", "gemini-environment")

    response = asyncio.run(
        activate_ai_provider(AIProviderActivation(provider="openrouter_free"))
    )
    loaded = load_config()

    assert response["active_provider"] == "openrouter_free"
    assert response["profiles"]["openrouter_free"]["active"] is True
    assert response["profiles"]["openrouter_auto"]["configured"] is True
    assert loaded.provider == "openrouter_free"
    assert loaded.model == "openrouter/free"


def test_activate_provider_function_switches_saved_profile(
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
            provider="gemini",
            api_key="AIza-gemini-key",
            model="gemini-test",
            provider_api_keys={
                "openai": "sk-openai-key",
                "gemini": "AIza-gemini-key",
            },
            provider_profiles=profiles,
        )
    )

    loaded = activate_provider("openai")

    assert loaded.provider == "openai"
    assert loaded.model == "gpt-test"
    assert loaded.configured is True


def test_disconnect_openrouter_removes_both_modes_and_falls_back(
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
        "openrouter_free": {
            "model": "openrouter/free",
            "fallback_1": "",
            "fallback_2": "",
            "base_url": "",
        },
    }
    save_config(
        AppConfig(
            provider="openrouter_free",
            api_key="sk-or-openrouter-key",
            model="openrouter/free",
            provider_api_keys={
                "gemini": "AIza-gemini-key",
                "openrouter": "sk-or-openrouter-key",
            },
            provider_profiles=profiles,
        )
    )
    activate_provider("openrouter_free")

    loaded = disconnect_provider("openrouter_free")

    assert loaded.provider == "gemini"
    assert loaded.configured is True
    assert loaded.key_is_saved("openrouter_auto") is False
    assert loaded.key_is_saved("openrouter_free") is False
    assert loaded.is_provider_configured("openrouter_auto") is False
    assert loaded.is_provider_configured("openrouter_free") is False
