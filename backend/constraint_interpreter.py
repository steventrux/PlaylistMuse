"""Multilingual hard-constraint interpretation using the configured AI provider."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx

from backend.config import AppConfig

OPENROUTER_PROVIDERS = {"openrouter_auto", "openrouter_free"}
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
CACHE_TTL_SECONDS = 30 * 24 * 60 * 60

SYSTEM_PROMPT = """You extract hard music-selection constraints from playlist requests written in any language.
Return JSON only. Separate mandatory filters from stylistic references.

A direct request is mandatory:
- music by Metallica / musica dei Metallica / Metallica songs
- rock from the 1990s / rock anni '90
- songs before 2000, after 2010, from 1995 onward
- tracks from a named album
- exclude Nirvana / no songs from Load

A similarity or stylistic reference is NOT mandatory:
- music like Metallica / simile ai Metallica
- 1990s-style rock / con sonorità anni '90
- inspired by Rumours

Return exactly this object:
{
  "allowed_artists": [],
  "excluded_artists": [],
  "allowed_albums": [],
  "excluded_albums": [],
  "release_year": null,
  "release_year_from": null,
  "release_year_to": null,
  "artist_country": null,
  "confidence": "high|medium|low"
}

Rules:
- Preserve artist and album names in their canonical-looking form.
- Use first-release year, not remaster, deluxe, reissue or compilation year.
- A decade means its full inclusive range: 1990s = 1990 through 1999.
- "before 2000" means release_year_to 1999; "after 2010" means release_year_from 2011.
- "from 1995 onward" means release_year_from 1995.
- Multiple allowed artists are alternatives: each track may be by any one of them.
- Include collaborators when the requested artist appears in official artist credits.
- Do not infer a hard constraint from mood, genre similarity, inspiration, vibe or sound-alike wording.
- Use null and empty arrays when no hard constraint exists.
"""


def _cache_path() -> Path:
    root = Path(os.getenv("PLAYLISTMUSE_DATA_DIR", "data"))
    return root / "constraint_interpretation_cache.sqlite3"


def _cache_key(config: AppConfig, prompt: str) -> str:
    source = f"{config.provider}|{config.model}|{prompt}".encode("utf-8")
    return hashlib.sha256(source).hexdigest()


def _connect() -> sqlite3.Connection:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS constraint_interpretation_cache (
            cache_key TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            expires_at REAL NOT NULL
        )
        """
    )
    return connection


def _read_cache(config: AppConfig, prompt: str) -> dict[str, Any] | None:
    try:
        with _connect() as connection:
            row = connection.execute(
                "SELECT payload, expires_at FROM constraint_interpretation_cache WHERE cache_key = ?",
                (_cache_key(config, prompt),),
            ).fetchone()
            if not row or float(row["expires_at"]) <= time.time():
                return None
            payload = json.loads(str(row["payload"]))
            return payload if isinstance(payload, dict) else None
    except (sqlite3.Error, ValueError, TypeError, json.JSONDecodeError):
        return None


def _write_cache(config: AppConfig, prompt: str, payload: dict[str, Any]) -> None:
    try:
        with _connect() as connection:
            connection.execute(
                """
                INSERT INTO constraint_interpretation_cache(cache_key, payload, expires_at)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                  payload = excluded.payload,
                  expires_at = excluded.expires_at
                """,
                (
                    _cache_key(config, prompt),
                    json.dumps(payload, ensure_ascii=False),
                    time.time() + CACHE_TTL_SECONDS,
                ),
            )
    except (sqlite3.Error, TypeError, ValueError):
        return


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("No JSON object returned")
    payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Constraint payload is not an object")
    return payload


def _gemini_text(data: dict[str, Any]) -> str:
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("Gemini returned no candidates")
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    return "".join(
        str(part.get("text", "")) for part in (parts or []) if isinstance(part, dict)
    ).strip()


def _openai_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("Provider returned no choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise ValueError("Provider returned no text")
    return content


async def _request(config: AppConfig, prompt: str) -> str:
    model = config.model_chain[0]
    timeout = httpx.Timeout(45.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        if config.provider == "gemini":
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": config.api_key, "content-type": "application/json"},
                json={
                    "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0,
                        "maxOutputTokens": 800,
                        "responseMimeType": "application/json",
                    },
                },
            )
            response.raise_for_status()
            return _gemini_text(response.json())

        if config.provider == "anthropic":
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": config.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 800,
                    "temperature": 0,
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
            data = response.json()
            content = data.get("content")
            if not isinstance(content, list) or not content:
                raise ValueError("Anthropic returned no content")
            return str(content[0].get("text", ""))

        if config.provider == "ollama":
            response = await client.post(
                f"{config.base_url.rstrip('/')}/api/chat",
                json={
                    "model": model,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0},
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                },
            )
            response.raise_for_status()
            return str(response.json().get("message", {}).get("content", ""))

        if config.provider in OPENROUTER_PROVIDERS:
            base_url = OPENROUTER_BASE_URL
            headers = {
                "authorization": f"Bearer {config.api_key}",
                "content-type": "application/json",
                "http-referer": "https://github.com/steventrux/PlaylistMuse",
                "x-title": "PlaylistMuse",
            }
        else:
            base_url = config.base_url.rstrip("/") if config.base_url else "https://api.openai.com/v1"
            headers = {"content-type": "application/json"}
            if config.api_key:
                headers["authorization"] = f"Bearer {config.api_key}"

        response = await client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json={
                "model": model,
                "temperature": 0,
                "max_tokens": 800,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            },
        )
        response.raise_for_status()
        return _openai_text(response.json())


async def interpret_constraints(config: AppConfig, prompt: str) -> dict[str, Any] | None:
    """Interpret multilingual constraints, returning None on any provider failure."""
    if not config.configured:
        return None
    cached = _read_cache(config, prompt)
    if cached is not None:
        return cached
    try:
        payload = _extract_json(await _request(config, prompt))
    except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError):
        return None
    _write_cache(config, prompt, payload)
    return payload
