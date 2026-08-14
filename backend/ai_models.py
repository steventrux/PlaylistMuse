"""Discover text-generation models available to each configured AI provider."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from backend.config import AppConfig

OPENROUTER_FIXED_MODELS = {
    "openrouter_auto": "openrouter/auto",
    "openrouter_free": "openrouter/free",
}
PROVIDERS_WITH_OPTIONAL_KEYS = {"ollama", "custom"}
MODEL_DISCOVERY_TIMEOUT = 15.0


@dataclass(slots=True)
class ProviderModels:
    """Models reported by a provider, with an optional verified recency signal.

    ``recommended_model`` and ``fallback_order`` are populated only when the provider
    exposes a genuine, verifiable recency signal (an official alias or a real
    creation timestamp) -- never guessed from a model's name alone.
    """

    models: list[str]
    recommended_model: str | None = None
    fallback_order: list[str] | None = field(default=None)


ModelLoader = Callable[[httpx.AsyncClient, AppConfig], Awaitable[ProviderModels]]


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


def _model_entries(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


_UNSTABLE_MODEL_TERMS = ("preview", "experimental", "exp-", "eap")


def _is_usable_model(model: str) -> bool:
    """Exclude preview/experimental/early-access models from selection entirely.

    These are unsuited for production use (unstable behaviour, no reliability guarantee,
    sometimes narrowly specialized like a video-only early-access build) -- excluded from
    the reported ``models`` list itself, not just from the automatic fallback chain.
    """
    lowered = model.casefold()
    return not any(term in lowered for term in _UNSTABLE_MODEL_TERMS)


def _recommendation_from_epoch(
    entries: list[dict[str, Any]], key: str
) -> tuple[str | None, list[str] | None]:
    """Rank entries by a real Unix-epoch creation timestamp (e.g. OpenAI's ``created``)."""
    dated: list[tuple[str, float]] = []
    for item in entries:
        model_id = str(item.get("id", "")).strip()
        raw = item.get(key)
        if (
            not model_id
            or not _is_usable_model(model_id)
            or isinstance(raw, bool)
            or not isinstance(raw, (int, float))
            or raw <= 0
        ):
            continue
        dated.append((model_id, float(raw)))
    if not dated:
        return None, None
    dated.sort(key=lambda pair: pair[1], reverse=True)
    ordered = _unique([model_id for model_id, _ in dated])
    return ordered[0], ordered[1:]


def _recommendation_from_iso8601(
    entries: list[dict[str, Any]], key: str
) -> tuple[str | None, list[str] | None]:
    """Rank entries by a real ISO-8601 creation timestamp (e.g. Anthropic's ``created_at``)."""
    dated: list[tuple[str, datetime]] = []
    for item in entries:
        model_id = str(item.get("id", "")).strip()
        raw = item.get(key)
        if not model_id or not _is_usable_model(model_id):
            continue
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        except ValueError:
            continue
        dated.append((model_id, parsed))
    if not dated:
        return None, None
    dated.sort(key=lambda pair: pair[1], reverse=True)
    ordered = _unique([model_id for model_id, _ in dated])
    return ordered[0], ordered[1:]


_GEMINI_FLASH_LATEST_ALIAS = "gemini-flash-latest"
_GEMINI_VERSION_RE = re.compile(r"^gemini-(\d+)\.(\d+)")


def _gemini_recency_sort_key(model: str) -> tuple[int, int, int]:
    match = _GEMINI_VERSION_RE.match(model)
    if not match:
        return (-1, 0, 0)
    is_flash = 1 if "flash" in model.casefold() else 0
    return (int(match.group(1)), int(match.group(2)), is_flash)


def _gemini_recommendation(
    models: list[str],
) -> tuple[str | None, list[str] | None]:
    """Use Google's own flash-tier ``-latest`` alias as the only verified recency signal.

    Gemini's model-list API exposes no reliable release-date field (``version`` is
    inconsistent, and the only date appears as free text inside ``description``), so
    anything else would be a guess rather than a verified signal.
    """
    if _GEMINI_FLASH_LATEST_ALIAS not in models:
        return None, None
    remaining = sorted(
        (
            model
            for model in models
            if model != _GEMINI_FLASH_LATEST_ALIAS and _is_usable_model(model)
        ),
        key=_gemini_recency_sort_key,
        reverse=True,
    )
    return _GEMINI_FLASH_LATEST_ALIAS, remaining


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


async def _gemini_models(client: httpx.AsyncClient, config: AppConfig) -> ProviderModels:
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
    recommended, fallback_order = _gemini_recommendation(models)
    return ProviderModels(
        models=models,
        recommended_model=recommended,
        fallback_order=fallback_order,
    )


async def _openai_models(client: httpx.AsyncClient, config: AppConfig) -> ProviderModels:
    payload = await _request_json(
        client,
        "GET",
        "https://api.openai.com/v1/models",
        provider_label="OpenAI",
        headers={"authorization": f"Bearer {config.api_key}"},
    )
    entries = [
        item
        for item in _model_entries(payload)
        if _is_openai_chat_model(str(item.get("id", "")).strip())
    ]
    models = _unique([str(item.get("id", "")).strip() for item in entries])
    recommended, fallback_order = _recommendation_from_epoch(entries, "created")
    return ProviderModels(
        models=models,
        recommended_model=recommended,
        fallback_order=fallback_order,
    )


async def _anthropic_models(client: httpx.AsyncClient, config: AppConfig) -> ProviderModels:
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
    entries = [
        item
        for item in _model_entries(payload)
        if str(item.get("id", "")).strip().startswith("claude-")
    ]
    models = _unique([str(item.get("id", "")).strip() for item in entries])
    recommended, fallback_order = _recommendation_from_iso8601(entries, "created_at")
    return ProviderModels(
        models=models,
        recommended_model=recommended,
        fallback_order=fallback_order,
    )


async def _ollama_models(client: httpx.AsyncClient, config: AppConfig) -> ProviderModels:
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
        return ProviderModels(models=[])
    # Ollama only reports when a model was pulled locally, not when it was released,
    # so there is no verifiable recency signal here -- the caller must choose explicitly.
    models = _unique(
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
    return ProviderModels(models=models)


async def _custom_models(client: httpx.AsyncClient, config: AppConfig) -> ProviderModels:
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
    # An arbitrary endpoint has no known schema/semantics for recency -- no recommendation.
    return ProviderModels(models=_openai_compatible_ids(payload))


MODEL_LOADERS: dict[str, ModelLoader] = {
    "gemini": _gemini_models,
    "openai": _openai_models,
    "anthropic": _anthropic_models,
    "ollama": _ollama_models,
    "custom": _custom_models,
}


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
            "recommended_model": None,
            "fallback_order": None,
        }

    loader = MODEL_LOADERS.get(config.provider)
    if loader is None:
        raise ModelDiscoveryError("Unknown AI provider.")

    if (
        config.provider not in PROVIDERS_WITH_OPTIONAL_KEYS
        and not config.api_key.strip()
    ):
        raise ModelDiscoveryError("Save or enter an API key to load available models.")

    async with httpx.AsyncClient(
        timeout=MODEL_DISCOVERY_TIMEOUT,
        follow_redirects=True,
    ) as client:
        result = await loader(client, config)

    usable_models = [model for model in result.models if _is_usable_model(model)]
    models = _sort_models(usable_models, config.model)
    if not models:
        raise ModelDiscoveryError(
            "The provider did not report any compatible text-generation models."
        )

    model_set = set(models)
    recommended_model = (
        result.recommended_model if result.recommended_model in model_set else None
    )
    fallback_order = (
        [model for model in result.fallback_order if model in model_set]
        if result.fallback_order
        else None
    ) or None

    return {
        "provider": config.provider,
        "models": models,
        "current_model": config.model,
        "fixed": False,
        "source": "provider_api",
        "recommended_model": recommended_model,
        "fallback_order": fallback_order,
    }
