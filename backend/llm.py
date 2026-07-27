"""Provider-neutral playlist candidate generation."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from backend.config import AppConfig

SYSTEM_PROMPT = """You are PlaylistMuse, a music playlist curator.
Return only a JSON array. Each item must contain exactly two string fields:
\"artist\" and \"title\". Choose real released tracks that match the request.
Do not include commentary, markdown, live versions, remixes, or covers unless
explicitly requested. Avoid duplicate artists when possible.
"""


def _extract_json(text: str) -> list[dict[str, str]]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start < 0 or end <= start:
        raise ValueError("The AI provider did not return a JSON track list.")
    payload: Any = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, list):
        raise ValueError("The AI provider returned an invalid playlist format.")

    tracks: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        artist = str(item.get("artist", "")).strip()
        title = str(item.get("title", "")).strip()
        if artist and title:
            tracks.append({"artist": artist, "title": title})
    if not tracks:
        raise ValueError("The AI provider returned no usable tracks.")
    return tracks


def _content_from_openai(data: dict[str, Any]) -> str:
    return str(data["choices"][0]["message"]["content"])


async def generate_candidates(config: AppConfig, prompt: str, count: int) -> list[dict[str, str]]:
    if not config.configured:
        raise ValueError("Configure an AI provider before generating a playlist.")

    user_prompt = f"Create {count} tracks for this request: {prompt}"
    timeout = httpx.Timeout(60.0, connect=10.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        if config.provider == "gemini":
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{config.model}:generateContent"
            )
            response = await client.post(
                url,
                params={"key": config.api_key},
                json={
                    "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                    "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json"},
                },
            )
            response.raise_for_status()
            data = response.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]

        elif config.provider == "anthropic":
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": config.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": config.model,
                    "max_tokens": 4096,
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": user_prompt}],
                },
            )
            response.raise_for_status()
            text = response.json()["content"][0]["text"]

        elif config.provider == "ollama":
            response = await client.post(
                f"{config.base_url.rstrip('/')}/api/chat",
                json={
                    "model": config.model,
                    "stream": False,
                    "format": "json",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
            response.raise_for_status()
            text = response.json()["message"]["content"]

        else:
            base_url = config.base_url.rstrip("/") if config.base_url else "https://api.openai.com/v1"
            headers = {"content-type": "application/json"}
            if config.api_key:
                headers["authorization"] = f"Bearer {config.api_key}"
            response = await client.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json={
                    "model": config.model,
                    "temperature": 0.7,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
            response.raise_for_status()
            text = _content_from_openai(response.json())

    return _extract_json(text)[:count]
