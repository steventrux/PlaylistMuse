"""Configuration persistence for PlaylistMuse."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.getenv("PLAYLISTMUSE_DATA_DIR", "data"))
CONFIG_PATH = DATA_DIR / "config.json"
OPENROUTER_PROVIDERS = {"openrouter_auto", "openrouter_free"}


def api_key_slot(provider: str) -> str:
    """Return the storage slot used by a provider's API key."""
    return "openrouter" if provider in OPENROUTER_PROVIDERS else provider


@dataclass(slots=True)
class AppConfig:
    provider: str = ""
    api_key: str = ""
    model: str = ""
    fallback_1: str = ""
    fallback_2: str = ""
    base_url: str = ""
    provider_api_keys: dict[str, str] = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        if not self.provider or not self.model:
            return False
        if self.provider == "ollama":
            return bool(self.base_url)
        return bool(self.api_key or (self.provider == "custom" and self.base_url))

    @property
    def model_chain(self) -> list[str]:
        """Return the primary model followed by unique configured fallbacks."""
        models: list[str] = []
        for value in (self.model, self.fallback_1, self.fallback_2):
            model = value.strip()
            if model and model not in models:
                models.append(model)
        return models

    def key_is_saved(self, provider: str) -> bool:
        """Return whether an API key is stored for the requested provider."""
        return bool(self.provider_api_keys.get(api_key_slot(provider), "").strip())


def _environment_or_saved(name: str, saved: str = "") -> str:
    """Use a non-empty environment override, otherwise keep the saved value."""
    environment_value = os.getenv(name)
    if environment_value is not None and environment_value.strip():
        return environment_value.strip()
    return str(saved or "").strip()


def _saved_api_keys(values: dict[str, Any], provider: str) -> dict[str, str]:
    """Load the per-provider key store and migrate older key formats."""
    raw_keys = values.get("api_keys", {})
    keys: dict[str, str] = {}
    if isinstance(raw_keys, dict):
        for name, value in raw_keys.items():
            key_name = api_key_slot(str(name).strip())
            key_value = str(value).strip()
            if key_name and key_value:
                keys[key_name] = key_value

    legacy_key = str(values.get("api_key", "") or "").strip()
    slot = api_key_slot(provider)
    if slot and legacy_key and slot not in keys:
        keys[slot] = legacy_key
    return keys


def load_config() -> AppConfig:
    values: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        try:
            loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            values = loaded if isinstance(loaded, dict) else {}
        except (OSError, json.JSONDecodeError):
            values = {}

    provider = _environment_or_saved(
        "PLAYLISTMUSE_AI_PROVIDER", str(values.get("provider", ""))
    )
    provider_api_keys = _saved_api_keys(values, provider)
    slot = api_key_slot(provider)
    saved_active_key = provider_api_keys.get(slot, "")
    active_key = _environment_or_saved("PLAYLISTMUSE_AI_API_KEY", saved_active_key)
    if slot and active_key:
        provider_api_keys[slot] = active_key

    return AppConfig(
        provider=provider,
        api_key=active_key,
        model=_environment_or_saved(
            "PLAYLISTMUSE_AI_MODEL", str(values.get("model", ""))
        ),
        fallback_1=_environment_or_saved(
            "PLAYLISTMUSE_AI_FALLBACK_1", str(values.get("fallback_1", ""))
        ),
        fallback_2=_environment_or_saved(
            "PLAYLISTMUSE_AI_FALLBACK_2", str(values.get("fallback_2", ""))
        ),
        base_url=_environment_or_saved(
            "PLAYLISTMUSE_AI_BASE_URL", str(values.get("base_url", ""))
        ),
        provider_api_keys=provider_api_keys,
    )


def save_config(config: AppConfig) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    keys = {
        api_key_slot(name): value
        for name, value in config.provider_api_keys.items()
        if name.strip() and value.strip()
    }
    slot = api_key_slot(config.provider)
    if slot and config.api_key:
        keys[slot] = config.api_key

    payload = {
        "provider": config.provider,
        "model": config.model,
        "fallback_1": config.fallback_1,
        "fallback_2": config.fallback_2,
        "base_url": config.base_url,
        "api_keys": keys,
    }

    temporary = CONFIG_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(CONFIG_PATH)
