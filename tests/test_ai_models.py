from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.ai_models import (
    MODEL_LOADERS,
    PROVIDERS_WITH_OPTIONAL_KEYS,
    ModelDiscoveryError,
    _anthropic_models,
    _gemini_models,
    _is_gemini_text_model,
    _is_ollama_chat_model,
    _is_openai_chat_model,
    _ollama_models,
    _openai_compatible_ids,
    _openai_models,
    discover_provider_models,
)
from backend.config import AppConfig
from backend.youtube_routes import AIModelDiscoveryRequest, get_available_ai_models


def _run_loader(loader, config: AppConfig, handler) -> list[str]:
    async def run() -> list[str]:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await loader(client, config)

    return asyncio.run(run())


def test_openai_model_filter_keeps_chat_models_only() -> None:
    assert _is_openai_chat_model("gpt-5-mini")
    assert _is_openai_chat_model("o4-mini")
    assert not _is_openai_chat_model("gpt-image-1")
    assert not _is_openai_chat_model("gpt-4o-realtime-preview")
    assert not _is_openai_chat_model("text-embedding-3-small")
    assert not _is_openai_chat_model("gpt-5-pro")
    assert not _is_openai_chat_model("gpt-5-codex")


def test_gemini_model_filter_excludes_non_text_generation_variants() -> None:
    assert _is_gemini_text_model("gemini-3.5-flash")
    assert _is_gemini_text_model("gemini-3.1-pro-preview")
    assert not _is_gemini_text_model("gemini-embedding-001")
    assert not _is_gemini_text_model("gemini-2.5-flash-image")
    assert not _is_gemini_text_model("gemini-2.5-flash-live")
    assert not _is_gemini_text_model("gemini-deep-research-preview")


def test_ollama_model_filter_excludes_embedding_only_models() -> None:
    assert _is_ollama_chat_model("qwen3:8b")
    assert _is_ollama_chat_model("llama3.1:8b")
    assert not _is_ollama_chat_model("nomic-embed-text")
    assert not _is_ollama_chat_model("bge-m3")


def test_openai_compatible_model_ids_are_unique() -> None:
    payload = {
        "data": [
            {"id": "model-a"},
            {"id": "model-a"},
            {"id": "model-b"},
            {"missing": "id"},
        ]
    }
    assert _openai_compatible_ids(payload) == ["model-a", "model-b"]


def test_dynamic_provider_loaders_are_registered_once() -> None:
    assert set(MODEL_LOADERS) == {
        "gemini",
        "openai",
        "anthropic",
        "ollama",
        "custom",
    }
    assert PROVIDERS_WITH_OPTIONAL_KEYS == {"ollama", "custom"}


def test_gemini_loader_uses_generation_methods_and_text_filter() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1beta/models"
        assert request.headers["x-goog-api-key"] == "gemini-key"
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": "models/gemini-3.5-flash",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                    {
                        "name": "models/gemini-embedding-001",
                        "supportedGenerationMethods": ["embedContent"],
                    },
                    {
                        "name": "models/gemini-2.5-flash-image",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                ]
            },
        )

    models = _run_loader(
        _gemini_models,
        AppConfig(provider="gemini", api_key="gemini-key"),
        handler,
    )
    assert models == ["gemini-3.5-flash"]


def test_openai_loader_filters_non_chat_models() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        assert request.headers["authorization"] == "Bearer openai-key"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "gpt-5-mini"},
                    {"id": "gpt-image-1"},
                    {"id": "text-embedding-3-small"},
                    {"id": "o4-mini"},
                ]
            },
        )

    models = _run_loader(
        _openai_models,
        AppConfig(provider="openai", api_key="openai-key"),
        handler,
    )
    assert models == ["gpt-5-mini", "o4-mini"]


def test_anthropic_loader_keeps_claude_models() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        assert request.headers["x-api-key"] == "anthropic-key"
        assert request.headers["anthropic-version"] == "2023-06-01"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "claude-sonnet-4-5"},
                    {"id": "claude-haiku-4-5"},
                    {"id": "other-model"},
                ]
            },
        )

    models = _run_loader(
        _anthropic_models,
        AppConfig(provider="anthropic", api_key="anthropic-key"),
        handler,
    )
    assert models == ["claude-sonnet-4-5", "claude-haiku-4-5"]


def test_ollama_loader_keeps_installed_chat_models() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(
            200,
            json={
                "models": [
                    {"model": "qwen3:8b"},
                    {"name": "llama3.1:8b"},
                    {"model": "nomic-embed-text"},
                ]
            },
        )

    models = _run_loader(
        _ollama_models,
        AppConfig(provider="ollama", base_url="http://ollama.test"),
        handler,
    )
    assert models == ["qwen3:8b", "llama3.1:8b"]


def test_provider_requiring_key_fails_before_network_call() -> None:
    with pytest.raises(
        ModelDiscoveryError,
        match="Save or enter an API key",
    ):
        asyncio.run(discover_provider_models(AppConfig(provider="gemini")))


def test_openrouter_modes_use_fixed_router_models() -> None:
    auto = asyncio.run(
        discover_provider_models(AppConfig(provider="openrouter_auto"))
    )
    free = asyncio.run(
        discover_provider_models(AppConfig(provider="openrouter_free"))
    )

    assert auto == {
        "provider": "openrouter_auto",
        "models": ["openrouter/auto"],
        "current_model": "openrouter/auto",
        "fixed": True,
        "source": "provider_router",
    }
    assert free["models"] == ["openrouter/free"]
    assert free["fixed"] is True


def test_ai_models_route_supports_fixed_openrouter_without_credentials() -> None:
    result = asyncio.run(
        get_available_ai_models(
            AIModelDiscoveryRequest(provider="openrouter_auto")
        )
    )
    assert result["models"] == ["openrouter/auto"]
    assert result["fixed"] is True
