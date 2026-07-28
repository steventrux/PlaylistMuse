"""Provider-neutral playlist generation with model fallbacks."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from typing import Any

import httpx

from backend.config import AppConfig

SYSTEM_PROMPT = """You are PlaylistMuse, an expert music playlist curator.
Return only one valid JSON object with exactly this structure:
{
  "title": "A short evocative playlist title",
  "description": "A concise description of the playlist's sound, mood and flow.",
  "tracks": [
    {
      "artist": "Artist name",
      "title": "Released track title",
      "description": "A concise description of this song's sound and character.",
      "reason": "Why this song belongs in this specific playlist and what role it plays."
    }
  ]
}

Rules:
- The title must be original, descriptive, 2 to 6 words, and no more than 70 characters.
- Do not simply repeat the user's prompt as the title.
- The playlist description must be 1 or 2 natural sentences, no more than 260 characters.
- The playlist description must explain the genres, mood, energy, era or listening context.
- Do not mention AI, the prompt, curation, or these instructions.
- Every track must be a real released song and contain exactly the four string fields shown above.
- Use the canonical concise song title, not a YouTube upload title, medley, full album or compilation.
- Each song description must be one concise sentence, no more than 180 characters.
- Each reason must be one concise sentence, no more than 220 characters, and must explain the song's contribution to this playlist's flow, mood, contrast or progression.
- Describe audible musical character; do not invent biographical or recording facts.
- Do not include live versions, remixes or covers unless explicitly requested.
- Never include the same song more than once, even if multiple uploads or versions exist.
- Avoid duplicate artists when possible.
- Return no commentary and no markdown outside the JSON object.
"""

OPENROUTER_PROVIDERS = {"openrouter_auto", "openrouter_free"}
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_BATCH_SIZE = 8
PROVIDER_BATCH_SIZES = {
    "openrouter_free": 6,
    "ollama": 6,
}


def _playlist_response_format(count: int, *, exact_count: bool = False) -> dict[str, Any]:
    """Return the JSON Schema used for OpenRouter structured output."""
    track_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "artist": {
                "type": "string",
                "minLength": 1,
                "maxLength": 160,
                "description": "Canonical artist name.",
            },
            "title": {
                "type": "string",
                "minLength": 1,
                "maxLength": 220,
                "description": "Canonical released song title.",
            },
            "description": {
                "type": "string",
                "minLength": 1,
                "maxLength": 320,
                "description": "One concise sentence describing the song's sound.",
            },
            "reason": {
                "type": "string",
                "minLength": 1,
                "maxLength": 400,
                "description": "One concise sentence explaining its role in this playlist.",
            },
        },
        "required": ["artist", "title", "description", "reason"],
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "playlist_muse_playlist",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "title": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 100,
                    },
                    "description": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 500,
                    },
                    "tracks": {
                        "type": "array",
                        "minItems": count if exact_count else 1,
                        "maxItems": count,
                        "items": track_schema,
                    },
                },
                "required": ["title", "description", "tracks"],
            },
        },
    }


def _openrouter_max_tokens(count: int) -> int:
    """Allow enough output for explanations without requesting an excessive limit."""
    return min(16_384, max(4_096, count * 320))


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("The AI provider did not return a JSON playlist object.")

    payload: Any = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("The AI provider returned an invalid playlist format.")

    title = str(payload.get("title", "")).strip()
    description = str(payload.get("description", "")).strip()
    raw_tracks = payload.get("tracks")

    if not title or len(title) > 100:
        raise ValueError("The AI provider returned an invalid playlist title.")
    if not description or len(description) > 500:
        raise ValueError("The AI provider returned an invalid playlist description.")
    if not isinstance(raw_tracks, list):
        raise ValueError("The AI provider did not return a JSON track list.")

    tracks: list[dict[str, str]] = []
    for item in raw_tracks:
        if not isinstance(item, dict):
            continue
        artist = str(item.get("artist", "")).strip()
        track_title = str(item.get("title", "")).strip()
        track_description = str(item.get("description", "")).strip()
        reason = str(item.get("reason", "")).strip()
        if artist and track_title and track_description and reason:
            tracks.append(
                {
                    "artist": artist,
                    "title": track_title,
                    "description": track_description[:320],
                    "reason": reason[:400],
                }
            )

    if not tracks:
        raise ValueError("The AI provider returned no usable tracks with explanations.")

    return {
        "title": title,
        "description": description,
        "tracks": tracks,
    }


def _normalize_identity(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(re.findall(r"[a-z0-9]+", without_accents.casefold()))


def _candidate_key(track: dict[str, str]) -> str:
    return (
        f"{_normalize_identity(track.get('artist', ''))}|"
        f"{_normalize_identity(track.get('title', ''))}"
    )


def _openrouter_error_message(error: Any) -> str:
    if isinstance(error, dict):
        message = error.get("message") or error.get("code")
        metadata = error.get("metadata")
        error_type = metadata.get("error_type") if isinstance(metadata, dict) else None
        if message and error_type:
            return f"{message} ({error_type})"
        if message:
            return str(message)
    return str(error or "Unknown OpenRouter error")


def _content_from_openai(data: dict[str, Any]) -> str:
    if data.get("error"):
        raise ValueError(_openrouter_error_message(data["error"]))

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("The AI provider returned no completion choices.")

    choice = choices[0]
    if not isinstance(choice, dict):
        raise ValueError("The AI provider returned an invalid completion choice.")
    if choice.get("error"):
        raise ValueError(_openrouter_error_message(choice["error"]))
    if choice.get("finish_reason") == "error":
        raise ValueError("The upstream model stopped with a provider error.")

    message = choice.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ValueError("The AI provider returned an empty completion.")
    return content


async def _request_model(
    client: httpx.AsyncClient,
    config: AppConfig,
    model: str,
    user_prompt: str,
    count: int,
    *,
    exact_count: bool = False,
) -> str:
    if config.provider == "gemini":
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent"
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
        return str(data["candidates"][0]["content"]["parts"][0]["text"])

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
                "max_tokens": 8192,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_prompt}],
            },
        )
        response.raise_for_status()
        return str(response.json()["content"][0]["text"])

    if config.provider == "ollama":
        response = await client.post(
            f"{config.base_url.rstrip('/')}/api/chat",
            json={
                "model": model,
                "stream": False,
                "format": "json",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        response.raise_for_status()
        return str(response.json()["message"]["content"])

    if config.provider in OPENROUTER_PROVIDERS:
        response = await client.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers={
                "authorization": f"Bearer {config.api_key}",
                "content-type": "application/json",
                "http-referer": "https://github.com/steventrux/PlaylistMuse",
                "x-title": "PlaylistMuse",
            },
            json={
                "model": model,
                "max_tokens": _openrouter_max_tokens(count),
                "stream": False,
                "response_format": _playlist_response_format(
                    count, exact_count=exact_count
                ),
                "plugins": [{"id": "response-healing"}],
                "provider": {"require_parameters": True},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        response.raise_for_status()
        return _content_from_openai(response.json())

    base_url = config.base_url.rstrip("/") if config.base_url else "https://api.openai.com/v1"
    headers = {"content-type": "application/json"}
    if config.api_key:
        headers["authorization"] = f"Bearer {config.api_key}"
    response = await client.post(
        f"{base_url}/chat/completions",
        headers=headers,
        json={
            "model": model,
            "temperature": 0.7,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        },
    )
    response.raise_for_status()
    return _content_from_openai(response.json())


def _batch_size(provider: str, count: int) -> int:
    preferred = PROVIDER_BATCH_SIZES.get(provider, DEFAULT_BATCH_SIZE)
    return min(preferred, count)


def _attempt_count(provider: str) -> int:
    return 2 if provider in OPENROUTER_PROVIDERS else 1


def _is_non_retryable_http_error(exc: Exception) -> bool:
    if not isinstance(exc, httpx.HTTPStatusError):
        return False
    return exc.response.status_code in {401, 402, 403}


def _batch_prompt(
    prompt: str,
    *,
    total_count: int,
    batch_count: int,
    collected: list[dict[str, str]],
) -> str:
    avoided = "\n".join(
        f"- {track['artist']} — {track['title']}" for track in collected
    )
    return (
        f"Build one cohesive playlist containing {total_count} tracks for this request:\n"
        f"{prompt}\n\n"
        f"Return the next batch of up to {batch_count} NEW tracks. "
        "The title and description must describe the complete playlist, not only this batch. "
        "Every returned song must be different from all songs already collected."
        + (f"\nSongs already collected and forbidden:\n{avoided}" if avoided else "")
    )


async def _generate_batched_draft(
    client: httpx.AsyncClient,
    config: AppConfig,
    prompt: str,
    count: int,
) -> dict[str, Any]:
    """Accumulate short responses from any provider until the playlist is complete."""
    tracks: list[dict[str, str]] = []
    seen: set[str] = set()
    title = ""
    description = ""
    errors: list[str] = []
    batch_size = _batch_size(config.provider, count)
    max_batches = min(20, max(4, math.ceil(count / batch_size) * 3))
    stalled_batches = 0

    for batch_number in range(1, max_batches + 1):
        remaining = count - len(tracks)
        if remaining <= 0:
            break

        requested = min(batch_size, remaining)
        user_prompt = _batch_prompt(
            prompt,
            total_count=count,
            batch_count=requested,
            collected=tracks,
        )
        batch_added = 0
        stop_for_credentials = False

        for model in config.model_chain:
            attempts = _attempt_count(config.provider)
            for attempt in range(1, attempts + 1):
                attempt_prompt = user_prompt
                if attempt > 1:
                    attempt_prompt += (
                        "\nThe previous response was invalid or added no new tracks. "
                        "Regenerate this batch with different songs and valid JSON only."
                    )
                try:
                    text = await _request_model(
                        client,
                        config,
                        model,
                        attempt_prompt,
                        requested,
                        exact_count=False,
                    )
                    draft = _extract_json(text)
                except Exception as exc:
                    errors.append(
                        f"batch {batch_number}/{max_batches}, {model} "
                        f"attempt {attempt}/{attempts}: {exc}"
                    )
                    if _is_non_retryable_http_error(exc):
                        stop_for_credentials = True
                        break
                    continue

                if not title:
                    title = draft["title"]
                    description = draft["description"]

                for track in draft["tracks"]:
                    key = _candidate_key(track)
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    tracks.append(track)
                    batch_added += 1
                    if len(tracks) >= count or batch_added >= requested:
                        break

                if batch_added:
                    break
                errors.append(
                    f"batch {batch_number}/{max_batches}, {model} "
                    f"attempt {attempt}/{attempts}: returned no new non-duplicate tracks"
                )

            if batch_added or stop_for_credentials:
                break

        if stop_for_credentials:
            break
        if batch_added:
            stalled_batches = 0
        else:
            stalled_batches += 1
            if stalled_batches >= 3:
                break

    if len(tracks) < count:
        detail = "; ".join(errors[-8:])
        raise ValueError(
            f"{config.provider} collected {len(tracks)} of {count} unique tracks after "
            f"{max_batches} short batches. {detail}".strip()
        )

    return {
        "title": title,
        "description": description,
        "tracks": tracks[:count],
    }


async def generate_playlist_draft(
    config: AppConfig, prompt: str, count: int
) -> dict[str, Any]:
    """Generate playlist metadata and canonical track candidates in short batches."""
    if not config.configured:
        raise ValueError("Configure an AI provider before generating a playlist.")

    timeout = httpx.Timeout(120.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await _generate_batched_draft(client, config, prompt, count)
