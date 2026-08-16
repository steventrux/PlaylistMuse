"""Configuration persistence for PlaylistMuse."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.storage import read_json_object, write_secure_json

DATA_DIR = Path(os.getenv("PLAYLISTMUSE_DATA_DIR", "data"))
CONFIG_PATH = DATA_DIR / "config.json"
OPENROUTER_PROVIDERS = {"openrouter_auto", "openrouter_free"}
OPENROUTER_MODELS = {
    "openrouter_auto": "openrouter/auto",
    "openrouter_free": "openrouter/free",
}
FALLBACK_FIELDS = tuple(f"fallback_{index}" for index in range(1, 9))
PROFILE_FIELDS = ("model", *FALLBACK_FIELDS, "base_url")


def api_key_slot(provider: str) -> str:
    """Return the storage slot used by a provider's API key."""
    return "openrouter" if provider in OPENROUTER_PROVIDERS else provider


def api_key_matches_provider(provider: str, api_key: str) -> bool:
    """Reject only unmistakable cross-provider key formats."""
    key = str(api_key or "").strip()
    if not key:
        return False
    if provider == "gemini" and key.startswith(("sk-or-", "sk-")):
        return False
    if provider in OPENROUTER_PROVIDERS and key.startswith("AIza"):
        return False
    return not (
        provider in {"openai", "anthropic"} and key.startswith("sk-or-")
    )


def _normalize_profile(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return dict.fromkeys(PROFILE_FIELDS, "")
    return {
        field_name: str(raw.get(field_name, "") or "").strip()
        for field_name in PROFILE_FIELDS
    }


def _profile_with_shared_defaults(
    provider: str,
    profile: dict[str, str],
    keys: dict[str, str],
) -> dict[str, str]:
    normalized = _normalize_profile(profile)
    if (
        provider in OPENROUTER_MODELS
        and keys.get("openrouter", "").strip()
        and not normalized["model"]
    ):
        normalized["model"] = OPENROUTER_MODELS[provider]
    return normalized


def _profile_is_configured(
    provider: str,
    profile: dict[str, str],
    api_key: str,
) -> bool:
    if not provider or not profile.get("model", "").strip():
        return False
    if provider == "ollama":
        return bool(profile.get("base_url", "").strip())
    if (
        provider == "custom"
        and profile.get("base_url", "").strip()
        and not api_key.strip()
    ):
        return True
    return api_key_matches_provider(provider, api_key)


@dataclass(slots=True)
class AppConfig:
    provider: str = ""
    api_key: str = ""
    model: str = ""
    fallback_1: str = ""
    fallback_2: str = ""
    fallback_3: str = ""
    fallback_4: str = ""
    fallback_5: str = ""
    fallback_6: str = ""
    fallback_7: str = ""
    fallback_8: str = ""
    base_url: str = ""
    provider_api_keys: dict[str, str] = field(default_factory=dict)
    provider_profiles: dict[str, dict[str, str]] = field(default_factory=dict)

    def _own_profile(self) -> dict[str, str]:
        return {field_name: getattr(self, field_name).strip() for field_name in PROFILE_FIELDS}

    @property
    def configured(self) -> bool:
        return _profile_is_configured(self.provider, self._own_profile(), self.api_key)

    @property
    def model_chain(self) -> list[str]:
        """Return the primary model followed by unique configured fallbacks, most-recent first."""
        models: list[str] = []
        for field_name in ("model", *FALLBACK_FIELDS):
            model = getattr(self, field_name).strip()
            if model and model not in models:
                models.append(model)
        return models

    def key_is_saved(self, provider: str) -> bool:
        """Return whether a compatible API key is stored for the requested provider."""
        key = self.provider_api_keys.get(api_key_slot(provider), "").strip()
        return api_key_matches_provider(provider, key)

    def profile_for(self, provider: str) -> dict[str, str]:
        """Return the saved model settings for one provider."""
        if provider == self.provider:
            profile = self._own_profile()
        else:
            profile = _normalize_profile(self.provider_profiles.get(provider, {}))
        return _profile_with_shared_defaults(
            provider,
            profile,
            self.provider_api_keys,
        )

    def configuration_for(self, provider: str) -> AppConfig:
        """Build an active configuration from a saved provider profile."""
        profile = self.profile_for(provider)
        return AppConfig(
            provider=provider,
            api_key=self.provider_api_keys.get(api_key_slot(provider), "").strip(),
            **profile,
            provider_api_keys=dict(self.provider_api_keys),
            provider_profiles={
                name: _normalize_profile(values)
                for name, values in self.provider_profiles.items()
            },
        )

    def is_provider_configured(self, provider: str) -> bool:
        """Return whether a stored provider profile can be used now."""
        return self.configuration_for(provider).configured


def _environment_or_saved(
    name: str,
    saved: str = "",
    *,
    enabled: bool = True,
) -> str:
    """Use an enabled non-empty environment override, otherwise keep saved data."""
    if enabled:
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


def _saved_profiles(values: dict[str, Any], provider: str) -> dict[str, dict[str, str]]:
    """Load provider profiles and migrate the former single-profile format."""
    profiles: dict[str, dict[str, str]] = {}
    raw_profiles = values.get("profiles", {})
    if isinstance(raw_profiles, dict):
        for name, raw_profile in raw_profiles.items():
            profile_name = str(name).strip()
            if profile_name:
                profiles[profile_name] = _normalize_profile(raw_profile)

    if provider:
        legacy_profile = {
            field_name: str(values.get(field_name, "") or "").strip()
            for field_name in PROFILE_FIELDS
        }
        if any(legacy_profile.values()):
            current = profiles.get(provider, _normalize_profile({}))
            profiles[provider] = {
                field_name: legacy_profile[field_name] or current[field_name]
                for field_name in PROFILE_FIELDS
            }
    return profiles


def _materialize_openrouter_profiles(
    profiles: dict[str, dict[str, str]],
    keys: dict[str, str],
) -> None:
    if not keys.get("openrouter", "").strip():
        return
    for provider, model in OPENROUTER_MODELS.items():
        # A fixed router has no fallback chain -- every other field is always empty.
        profile = dict.fromkeys(PROFILE_FIELDS, "")
        profile["model"] = model
        profiles[provider] = profile


def _configured_provider_from_state(
    provider: str,
    profiles: dict[str, dict[str, str]],
    keys: dict[str, str],
) -> bool:
    profile = _profile_with_shared_defaults(
        provider,
        profiles.get(provider, {}),
        keys,
    )
    return _profile_is_configured(
        provider,
        profile,
        keys.get(api_key_slot(provider), ""),
    )


def _write_config_state(
    active_provider: str,
    profiles: dict[str, dict[str, str]],
    keys: dict[str, str],
) -> None:
    active_profile = _profile_with_shared_defaults(
        active_provider,
        profiles.get(active_provider, {}),
        keys,
    )
    payload = {
        "managed": True,
        "provider": active_provider,
        **active_profile,
        "api_keys": keys,
        "profiles": profiles,
    }
    write_secure_json(
        CONFIG_PATH,
        payload,
        temporary_path=CONFIG_PATH.with_suffix(".tmp"),
    )


def load_config() -> AppConfig:
    values = read_json_object(CONFIG_PATH)
    has_saved_state = bool(values)

    saved_provider = str(values.get("provider", "") or "").strip()
    environment_provider = str(os.getenv("PLAYLISTMUSE_AI_PROVIDER", "") or "").strip()
    provider = saved_provider if has_saved_state else environment_provider
    provider_api_keys = _saved_api_keys(values, provider)
    provider_profiles = _saved_profiles(values, saved_provider or provider)
    _materialize_openrouter_profiles(provider_profiles, provider_api_keys)
    active_profile = _profile_with_shared_defaults(
        provider,
        provider_profiles.get(provider, {}),
        provider_api_keys,
    )

    use_environment = not has_saved_state or provider == environment_provider
    slot = api_key_slot(provider)
    saved_active_key = provider_api_keys.get(slot, "")
    active_key = _environment_or_saved(
        "PLAYLISTMUSE_AI_API_KEY",
        saved_active_key,
        enabled=use_environment,
    )
    if slot and active_key:
        provider_api_keys[slot] = active_key
        _materialize_openrouter_profiles(provider_profiles, provider_api_keys)

    model = _environment_or_saved(
        "PLAYLISTMUSE_AI_MODEL",
        active_profile["model"],
        enabled=use_environment,
    )
    fallback_1 = _environment_or_saved(
        "PLAYLISTMUSE_AI_FALLBACK_1",
        active_profile["fallback_1"],
        enabled=use_environment,
    )
    fallback_2 = _environment_or_saved(
        "PLAYLISTMUSE_AI_FALLBACK_2",
        active_profile["fallback_2"],
        enabled=use_environment,
    )
    base_url = _environment_or_saved(
        "PLAYLISTMUSE_AI_BASE_URL",
        active_profile["base_url"],
        enabled=use_environment,
    )
    # fallback_3..fallback_8 are the automatic cascade -- always from the saved profile,
    # no per-slot environment override (unlike the primary model and fallback_1/2 above).
    extra_fallbacks = {name: active_profile[name] for name in FALLBACK_FIELDS[2:]}

    if provider:
        provider_profiles[provider] = {
            "model": model,
            "fallback_1": fallback_1,
            "fallback_2": fallback_2,
            "base_url": base_url,
            **extra_fallbacks,
        }

    return AppConfig(
        provider=provider,
        api_key=active_key,
        model=model,
        fallback_1=fallback_1,
        fallback_2=fallback_2,
        base_url=base_url,
        **extra_fallbacks,
        provider_api_keys=provider_api_keys,
        provider_profiles=provider_profiles,
    )


def save_config(config: AppConfig) -> None:
    """Save provider settings without replacing another active configured provider."""
    existing = read_json_object(CONFIG_PATH)
    existing_provider = str(existing.get("provider", "") or "").strip()
    profiles = _saved_profiles(existing, existing_provider)
    for name, values in config.provider_profiles.items():
        profile_name = str(name).strip()
        if profile_name:
            profiles[profile_name] = _normalize_profile(values)

    if config.provider:
        profiles[config.provider] = config._own_profile()

    keys = _saved_api_keys(existing, existing_provider)
    for name, value in config.provider_api_keys.items():
        key_name = api_key_slot(str(name).strip())
        key_value = str(value).strip()
        if key_name and key_value:
            keys[key_name] = key_value
    slot = api_key_slot(config.provider)
    if slot and config.api_key:
        keys[slot] = config.api_key.strip()

    _materialize_openrouter_profiles(profiles, keys)

    if _configured_provider_from_state(existing_provider, profiles, keys):
        active_provider = existing_provider
    else:
        active_provider = config.provider

    if not _configured_provider_from_state(active_provider, profiles, keys):
        active_provider = next(
            (
                provider
                for provider in profiles
                if _configured_provider_from_state(provider, profiles, keys)
            ),
            config.provider,
        )

    _write_config_state(active_provider, profiles, keys)


def activate_provider(provider: str) -> AppConfig:
    """Force one configured provider to become active."""
    existing = read_json_object(CONFIG_PATH)
    existing_provider = str(existing.get("provider", "") or "").strip()
    profiles = _saved_profiles(existing, existing_provider)
    keys = _saved_api_keys(existing, existing_provider)
    _materialize_openrouter_profiles(profiles, keys)
    if not _configured_provider_from_state(provider, profiles, keys):
        raise ValueError("Configure this AI provider before activating it.")
    _write_config_state(provider, profiles, keys)
    return load_config()


def disconnect_provider(provider: str) -> AppConfig:
    """Remove one stored AI provider and choose another configured provider if needed."""
    existing = read_json_object(CONFIG_PATH)
    existing_provider = str(existing.get("provider", "") or "").strip()
    profiles = _saved_profiles(existing, existing_provider)
    keys = _saved_api_keys(existing, existing_provider)

    targets = OPENROUTER_PROVIDERS if provider in OPENROUTER_PROVIDERS else {provider}
    for target in targets:
        profiles.pop(target, None)
    keys.pop(api_key_slot(provider), None)

    candidates = [
        existing_provider,
        "gemini",
        "openai",
        "anthropic",
        "openrouter_auto",
        "openrouter_free",
        "ollama",
        "custom",
        *profiles.keys(),
    ]
    active_provider = next(
        (
            candidate
            for candidate in dict.fromkeys(candidates)
            if candidate not in targets
            and _configured_provider_from_state(candidate, profiles, keys)
        ),
        "",
    )

    _write_config_state(active_provider, profiles, keys)
    return load_config()
