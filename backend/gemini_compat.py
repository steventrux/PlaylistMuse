"""Gemini generateContent compatibility and public-error hardening.

The generateContent REST endpoint expects responseMimeType and
responseJsonSchema directly inside generationConfig. This module installs a
small provider-specific override while leaving every other provider untouched.
"""

from __future__ import annotations

from typing import Any

import httpx

from backend import llm as _llm
from backend.config import AppConfig

_ORIGINAL_REQUEST_MODEL = _llm._request_model
_ORIGINAL_SAFE_ERROR_MESSAGE = _llm.safe_error_message

_GEMINI_SCHEMA_KEYS = {
    "$id",
    "$defs",
    "$ref",
    "$anchor",
    "type",
    "format",
    "title",
    "description",
    "enum",
    "items",
    "prefixItems",
    "minItems",
    "maxItems",
    "minimum",
    "maximum",
    "anyOf",
    "oneOf",
    "properties",
    "additionalProperties",
    "required",
    "propertyOrdering",
}


def _gemini_json_schema(value: Any) -> Any:
    """Keep only JSON Schema keywords supported by Gemini structured output."""
    if isinstance(value, list):
        return [_gemini_json_schema(item) for item in value]
    if not isinstance(value, dict):
        return value

    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        if key not in _GEMINI_SCHEMA_KEYS:
            continue
        if key == "properties" and isinstance(item, dict):
            cleaned[key] = {
                str(property_name): _gemini_json_schema(property_schema)
                for property_name, property_schema in item.items()
            }
        else:
            cleaned[key] = _gemini_json_schema(item)
    return cleaned


async def _request_model(
    client: httpx.AsyncClient,
    config: AppConfig,
    model: str,
    user_prompt: str,
    count: int,
    *,
    exact_count: bool = False,
) -> str:
    """Use the correct Gemini REST structured-output fields."""
    if config.provider != "gemini":
        return await _ORIGINAL_REQUEST_MODEL(
            client,
            config,
            model,
            user_prompt,
            count,
            exact_count=exact_count,
        )

    schema = _gemini_json_schema(
        _llm._playlist_json_schema(count, exact_count=exact_count)
    )
    response = await client.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={
            "x-goog-api-key": config.api_key,
            "content-type": "application/json",
        },
        json={
            "systemInstruction": {"parts": [{"text": _llm.SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "maxOutputTokens": min(65_536, max(8_192, count * 520)),
                "responseMimeType": "application/json",
                "responseJsonSchema": schema,
            },
        },
    )
    _llm._raise_for_provider(response, "Gemini")
    return _llm._gemini_text(response.json())


def _safe_error_message(error: Exception) -> str:
    """Keep user-visible failures concise after internal fallback attempts."""
    if isinstance(error, _llm.ProviderRequestError):
        return str(error)

    message = _ORIGINAL_SAFE_ERROR_MESSAGE(error)
    if message.startswith("The AI provider produced"):
        summary = message.split(".", 1)[0].strip()
        return f"{summary}. Try again or select another configured AI provider."
    return message


def install() -> None:
    """Install the override once during backend package import."""
    if getattr(_llm, "_playlistmuse_gemini_compat_installed", False):
        return
    _llm._request_model = _request_model
    _llm.safe_error_message = _safe_error_message
    _llm._playlistmuse_gemini_compat_installed = True
