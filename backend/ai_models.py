"""Discover text-generation models available to each configured AI provider."""

from __future__ import annotations

from typing import Any

import httpx

from backend.config import AppConfig

OPENROUTER_FIXED_MODELS = {
    "openrouter_auto": "openrouter/auto",
    "openrouter_free": "openrouter/free",
}
MODEL_DISCOVERY_TIMEOUT = 15.0


class ModelDiscoveryError(ValueError):
    """A public-safe error raised when a provider model list cannot be read."""


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _openai_compatible_ids(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    return _unique(
        [
            str(item.get("id", "")).strip()
            for item in data
            if isinstance(item, dict)
        ]
    )


def _is_openai_chat_model(model: str) -> bool:
    lowered = model.casefold()
    prefixes = ("gpt-", "chatgpt-", "o1", "o3", "o4", "o5")
    excluded = (
        "audio",
        "realtime",
        "transcribe",
        "tts",
        "image",
        "embedding",
        "moderation",
        "whisper",
        "codex",
        "computer-use",
        "search",
        "-pro",
    )
    return lowered.startswith(prefixes) and not any(term in lowered for term in excluded)


def _is_gemini_text_model(model: str) -> bool:
    lowered = model.casefold()
    excluded = (
        "embedding",
        "image",
        "imagen",
        "tts",
        "live",
        "robotics",
        "veo",
        "nano-banana",
        "deep-research",
        "computer-use",
    )
    return lowered.startswith("gemini-") and not any(term in lowered for term in excluded)


def _is_ollama_chat_model(model: str) -> bool:
    lowered = model.casefold()
    excluded = (
        "embed",
        "embedding",
        "nomic-bert",
        "all-minilm",
        "bge-",
        "clip",
    )
    return not any(term in lowered for term in excluded)


def _sort_models(models: list[str], current_model: str = "") -> list[str]:
    current = current_model.strip()

    def key(model: str) -> tuple[int, int, str]:
        lowered = model.casefold()
        current_rank = 0 if current and model == current else 1
        unstable_rank = 1 if any(
            term in lowered for term in ("preview", "experimental", "exp-")
        ) else 0
        return current_rank, unstable_rank, lowered

    return sorted(_unique(models), key=key)


async def _request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    provider_label: str,
    headers: dict[str, str] | None = None,
    params: dict[str, str | int] | None = None,
) -> dict[str, Any]:
    try:
        response = await client.request(method, url, headers=headers, params=params)
    except httpx.HTTPError as error:
        raise ModelDiscoveryError(
            f"{provider_label} model availability could not be checked."
        ) from error

    if response.status_code in {401, 403}:
        raise ModelDiscoveryError(
            f"{provider_label} rejected the saved API key or its permissions."
        )
    if not response.is_success:
        raise ModelDiscoveryError(
            f"{provider_label} model availability check failed ({response.status_code})."
        )
    try:
        payload = response.json()
    except ValueError as error:
        raise ModelDiscoveryError(
            f"{provider_label} returned an invalid model list."
        ) from error
    if not isinstance(payload, dict):
        raise ModelDiscoveryError(
            f"{provider_label} returned an invalid model list."
        )
    return payload


async def _gemini_models(client: httpx.AsyncClient, config: AppConfig) -> list[str]:
    payload = await _request_json(
        client,
        "GET",
        "https://generativelanguage.googleapis.com/v1beta/models",
        provider_label="Gemini",
        headers={"x-goog-api-key": config.api_key},
        params={"pageSize": 1000},
    )
    models: list[str] = []
    for item in payload.get("models", []):
        if not isinstance(item, dict):
            continue
        methods = item.get("supportedGenerationMethods", [])
        if "generateContent" not in methods:
            continue
        model = str(item.get("name", "")).removeprefix("models/").strip()
        if _is_gemini_text_model(model):
            models.append(model)
    return models


async def _openai_models(client: httpx.AsyncClient, config: AppConfig) -> list[str]:
    payload = await _request_json(
        client,
        "GET",
        "https://api.openai.com/v1/models",
        provider_label="OpenAI",
        headers={"authorization": f"Bearer {config.api_key}"},
    )
    return [
        model
        for model in _openai_compatible_ids(payload)
        if _is_openai_chat_model(model)
    ]


async def _anthropic_models(client: httpx.AsyncClient, config: AppConfig) -> list[str]:
    payload = await _request_json(
        client,
        "GET",
        "https://api.anthropic.com/v1/models",
        provider_label="Anthropic",
        headers={
            "x-api-key": config.api_key,
            "anthropic-version": "2023-06-01",
        },
        params={"limit": 1000},
    )
    return [
        model
        for model in _openai_compatible_ids(payload)
        if model.startswith("claude-")
    ]


async def _ollama_models(client: httpx.AsyncClient, config: AppConfig) -> list[str]:
    if not config.base_url.strip():
        raise ModelDiscoveryError("Enter the Ollama server URL first.")
    payload = await _request_json(
        client,
        "GET",
        f"{config.base_url.rstrip('/')}/api/tags",
        provider_label="Ollama",
    )
    raw_models = payload.get("models", [])
    if not isinstance(raw_models, list):
        return []
    return _unique(
        [
            model
            for item in raw_models
            if isinstance(item, dict)
            for model in [
                str(item.get("model") or item.get("name") or "").strip()
            ]
            if model and _is_ollama_chat_model(model)
        ]
    )


async def _custom_models(client: httpx.AsyncClient, config: AppConfig) -> list[str]:
    if not config.base_url.strip():
        raise ModelDiscoveryError("Enter the compatible API base URL first.")
    headers = (
        {"authorization": f"Bearer {config.api_key}"}
        if config.api_key.strip()
        else None
    )
    payload = await _request_json(
        client,
        "GET",
        f"{config.base_url.rstrip('/')}/models",
        provider_label="Compatible endpoint",
        headers=headers,
    )
    return _openai_compatible_ids(payload)


async def discover_provider_models(config: AppConfig) -> dict[str, Any]:
    """Return models visible to this provider configuration.

    The result is intentionally based on the provider's own model-list endpoint. It
    therefore reflects the saved or temporarily submitted API key, account policies,
    regional routing and, for Ollama, locally installed models.
    """

    fixed_model = OPENROUTER_FIXED_MODELS.get(config.provider)
    if fixed_model:
        return {
            "provider": config.provider,
            "models": [fixed_model],
            "current_model": fixed_model,
            "fixed": True,
            "source": "provider_router",
        }

    if config.provider not in {"ollama", "custom"} and not config.api_key.strip():
        raise ModelDiscoveryError("Save or enter an API key to load available models.")

    async with httpx.AsyncClient(
        timeout=MODEL_DISCOVERY_TIMEOUT,
        follow_redirects=True,
    ) as client:
        if config.provider == "gemini":
            models = await _gemini_models(client, config)
        elif config.provider == "openai":
            models = await _openai_models(client, config)
        elif config.provider == "anthropic":
            models = await _anthropic_models(client, config)
        elif config.provider == "ollama":
            models = await _ollama_models(client, config)
        elif config.provider == "custom":
            models = await _custom_models(client, config)
        else:
            raise ModelDiscoveryError("Unknown AI provider.")

    models = _sort_models(models, config.model)
    if not models:
        raise ModelDiscoveryError(
            "The provider did not report any compatible text-generation models."
        )
    return {
        "provider": config.provider,
        "models": models,
        "current_model": config.model,
        "fixed": False,
        "source": "provider_api",
    }
