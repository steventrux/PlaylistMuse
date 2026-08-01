from __future__ import annotations

import asyncio

from backend.ai_models import (
    _is_gemini_text_model,
    _is_ollama_chat_model,
    _is_openai_chat_model,
    _openai_compatible_ids,
    discover_provider_models,
)
from backend.config import AppConfig
from backend.youtube_routes import AIModelDiscoveryRequest, get_available_ai_models


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
