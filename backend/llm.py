"""Provider-neutral playlist generation with safe fallbacks."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from typing import Any

import httpx

from backend.config import AppConfig
from backend.constraint_interpreter import _dated_system_prompt
from backend.provider_rate_limits import (
    ProviderRateLimitedError,
    cooldown_seconds_for_response,
    format_cooldown,
    is_rate_limited,
    longest_remaining_cooldown,
    mark_rate_limited,
)

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

Curation protocol:
- Before producing JSON, silently build a constraint checklist from the request and any internal guidance.
- Apply requirements in this priority order: explicit mandatory constraints and placements; real-track identity and exclusions; the user's explicit core musical brief (genre or style, mood, energy, activity or listening context, and requested sound); requested structure, sequencing and progression; then generic coherence, variety, popularity and discovery preferences.
- Hard constraints define which tracks are eligible. Within that compliant set, treat every explicit non-mandatory musical preference as a substantive playlist-wide selection objective, not merely as title or description metadata and not merely as a tie-breaker.
- Do not collapse a request to its broad category, era, country, language or genre while ignoring an explicit mood, energy, activity, occasion or listening context. Every selected track must have a defensible role in that stated context; material contrasts belong only when the user asks for contrast or a progression that requires them.
- Never relax a mandatory requirement to improve a soft objective, and never let generic popularity, variety, novelty or discovery override an explicit user preference.
- Silently verify every selected song against the applicable hard constraints and against the songs already selected.
- If the request asks for ordering, alternation, sections, transitions or an energy progression, design the sequence deliberately rather than treating the playlist as an unordered bag of songs.
- Prefer canonical, confidently real released tracks over uncertain titles. When discovery or obscurity is requested, explore less obvious choices only while preserving factual confidence and all hard constraints.
- Before returning, silently verify the requested count, duplicate avoidance, explicit artist/song quotas, required inclusions and positional requirements.
- Before returning, silently verify that the playlist description does not state a specific number of songs, artists or years that contradicts what the final tracks array actually contains -- if the description mentions a count, era span or artist tally, recompute it from the finished tracks array rather than an earlier draft.
- Do not output this planning, checklist or verification. Return only the requested JSON; the short public `reason` field is not private analysis.

Rules:
- The title must be original, descriptive, 2 to 6 words, and no more than 70 characters.
- Do not simply repeat the user's prompt as the title.
- The playlist description must be 1 or 2 natural sentences, no more than 260 characters.
- The playlist description must explain the genres, mood, energy, era or listening context.
- If the description states a specific number of songs by an artist, a track count, or a year/era span, that number must exactly match the final tracks array -- never a count from an earlier draft.
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
    "gemini": 16,
    "openrouter_auto": 16,
    "anthropic": 16,
}

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

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_URL_RE = re.compile(r"https?://\S+")
_API_KEY_RE = re.compile(r"(?:AIza|sk-or-|sk-)[A-Za-z0-9_\-]{12,}")
_QUERY_KEY_RE = re.compile(r"\bkey=[^\s&]+", re.IGNORECASE)


class ProviderRequestError(ValueError):
    """A provider failure whose public message contains no credentials or raw URLs."""

    def __init__(self, provider: str, status_code: int | None, message: str) -> None:
        self.provider = provider
        self.status_code = status_code
        super().__init__(message)


def _track_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "artist": {"type": "string", "minLength": 1, "maxLength": 160},
            "title": {"type": "string", "minLength": 1, "maxLength": 220},
            "description": {"type": "string", "minLength": 1, "maxLength": 320},
            "reason": {"type": "string", "minLength": 1, "maxLength": 400},
        },
        "required": ["artist", "title", "description", "reason"],
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


def _playlist_json_schema(count: int, *, exact_count: bool = False) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": 100},
            "description": {"type": "string", "minLength": 1, "maxLength": 500},
            "tracks": {
                "type": "array",
                "minItems": count if exact_count else 1,
                "maxItems": count,
                "items": _track_schema(),
            },
        },
        "required": ["title", "description", "tracks"],
    }


def _playlist_response_format(count: int, *, exact_count: bool = False) -> dict[str, Any]:
    """Return the OpenRouter/OpenAI JSON Schema response format."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "playlist_muse_playlist",
            "strict": True,
            "schema": _playlist_json_schema(count, exact_count=exact_count),
        },
    }


def _openrouter_max_tokens(count: int) -> int:
    return min(32_768, max(4_096, count * 500))


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = _CODE_FENCE_RE.sub("", cleaned)
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
    return {"title": title, "description": description, "tracks": tracks}


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


def _unique_tracks(
    candidates: list[dict[str, str]], *, limit: int | None = None
) -> list[dict[str, str]]:
    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for track in candidates:
        key = _candidate_key(track)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(track)
        if limit is not None and len(unique) >= limit:
            break
    return unique


def _safe_provider_message(provider: str, response: httpx.Response) -> str:
    message = "The provider rejected the request."
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        raw_error = payload.get("error")
        if isinstance(raw_error, dict):
            raw_message = raw_error.get("message") or raw_error.get("status")
        else:
            raw_message = payload.get("message") or raw_error
        if raw_message:
            message = str(raw_message)

    message = _URL_RE.sub("", message)
    message = _API_KEY_RE.sub("[redacted]", message)
    message = " ".join(message.split()).strip(" ;,.")
    if response.status_code in {401, 403}:
        return f"{provider} rejected the saved API key or its permissions."
    if response.status_code == 429:
        return f"{provider} rate limit or quota reached. Try again later."
    return f"{provider} request failed ({response.status_code}): {message[:260]}"


def safe_error_message(error: Exception) -> str:
    """Return a concise public error without URLs, keys, request bodies or trace detail."""
    text = str(error)
    text = _URL_RE.sub("", text)
    text = _API_KEY_RE.sub("[redacted]", text)
    text = _QUERY_KEY_RE.sub("key=[redacted]", text)
    text = " ".join(text.split()).strip()
    message = text[:420] or "The AI provider could not complete the request."
    if message.startswith("The AI provider produced"):
        summary = message.split(".", 1)[0].strip()
        return f"{summary}. Try again or select another configured AI provider."
    return message


def _raise_for_provider(
    response: httpx.Response,
    provider: str,
    *,
    provider_key: str | None = None,
    model: str | None = None,
) -> None:
    if response.is_success:
        return
    if response.status_code == 429 and provider_key and model:
        mark_rate_limited(
            provider_key,
            model,
            cooldown_seconds=cooldown_seconds_for_response(response, provider_key),
        )
    raise ProviderRequestError(
        provider,
        response.status_code,
        _safe_provider_message(provider, response),
    )


def _content_from_openai(data: dict[str, Any]) -> str:
    error = data.get("error")
    if error:
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise ProviderRequestError("AI provider", None, str(message or "Provider error"))
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("The AI provider returned no completion choices.")
    choice = choices[0]
    if not isinstance(choice, dict) or choice.get("finish_reason") == "error":
        raise ValueError("The upstream model stopped with a provider error.")
    message = choice.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ValueError("The AI provider returned an empty completion.")
    return content


def _gemini_text(data: dict[str, Any]) -> str:
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        feedback = data.get("promptFeedback")
        if isinstance(feedback, dict) and feedback.get("blockReason"):
            raise ValueError(f"Gemini blocked the request: {feedback['blockReason']}")
        raise ValueError("Gemini returned no completion candidates.")
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    texts = [str(part.get("text", "")) for part in (parts or []) if isinstance(part, dict)]
    text = "".join(texts).strip()
    if not text:
        raise ValueError("Gemini returned an empty completion.")
    return text


async def _request_model(
    client: httpx.AsyncClient,
    config: AppConfig,
    model: str,
    user_prompt: str,
    count: int,
    *,
    exact_count: bool = False,
) -> str:
    if is_rate_limited(config.provider, model):
        raise ProviderRateLimitedError(f"{config.provider}/{model} is cached as rate-limited")

    dated_system_prompt = _dated_system_prompt(SYSTEM_PROMPT)

    if config.provider == "gemini":
        response = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={
                "x-goog-api-key": config.api_key,
                "content-type": "application/json",
            },
            json={
                "systemInstruction": {"parts": [{"text": dated_system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                "generationConfig": {
                    "maxOutputTokens": min(65_536, max(8_192, count * 520)),
                    "responseMimeType": "application/json",
                    "responseJsonSchema": _gemini_json_schema(
                        _playlist_json_schema(count, exact_count=exact_count)
                    ),
                },
            },
        )
        _raise_for_provider(response, "Gemini", provider_key=config.provider, model=model)
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
                "max_tokens": min(32_000, max(8_192, count * 500)),
                "system": dated_system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            },
        )
        _raise_for_provider(response, "Anthropic", provider_key=config.provider, model=model)
        data = response.json()
        content = data.get("content")
        if not isinstance(content, list) or not content:
            raise ValueError("Anthropic returned an empty completion.")
        return str(content[0].get("text", ""))

    if config.provider == "ollama":
        response = await client.post(
            f"{config.base_url.rstrip('/')}/api/chat",
            json={
                "model": model,
                "stream": False,
                "format": "json",
                "messages": [
                    {"role": "system", "content": dated_system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        _raise_for_provider(response, "Ollama", provider_key=config.provider, model=model)
        return str(response.json().get("message", {}).get("content", ""))

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
                    {"role": "system", "content": dated_system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        _raise_for_provider(response, "OpenRouter", provider_key=config.provider, model=model)
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
                {"role": "system", "content": dated_system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        },
    )
    _raise_for_provider(response, "OpenAI-compatible provider", provider_key=config.provider, model=model)
    return _content_from_openai(response.json())


def _batch_size(provider: str, count: int) -> int:
    return min(PROVIDER_BATCH_SIZES.get(provider, DEFAULT_BATCH_SIZE), count)


def _attempt_count(provider: str) -> int:
    return 2 if provider in OPENROUTER_PROVIDERS else 1


def _is_non_retryable_http_error(error: Exception) -> bool:
    if isinstance(error, ProviderRequestError):
        return error.status_code in {401, 402, 403}
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in {401, 402, 403}
    return False


def _complete_prompt(prompt: str, count: int) -> str:
    return f"Create a playlist containing exactly {count} tracks for this request:\n{prompt}"


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
        f"{prompt}\n\nReturn the next batch of up to {batch_count} NEW tracks. "
        "The title and description must describe the complete playlist, not only this batch. "
        "Every returned song must be different from all songs already collected."
        + (f"\nSongs already collected and forbidden:\n{avoided}" if avoided else "")
    )


async def _try_complete_request(
    client: httpx.AsyncClient,
    config: AppConfig,
    prompt: str,
    count: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    best_partial: dict[str, Any] | None = None
    errors: list[str] = []
    base_prompt = _complete_prompt(prompt, count)

    for model in config.model_chain:
        attempts = _attempt_count(config.provider)
        for attempt in range(1, attempts + 1):
            attempt_prompt = base_prompt
            if attempt > 1:
                attempt_prompt += (
                    "\nRegenerate the full playlist from scratch. The previous response was "
                    "invalid or incomplete. Return all requested tracks in valid JSON."
                )
            try:
                text = await _request_model(
                    client,
                    config,
                    model,
                    attempt_prompt,
                    count,
                    exact_count=True,
                )
                draft = _extract_json(text)
                draft["tracks"] = _unique_tracks(draft["tracks"], limit=count)
            except Exception as error:
                errors.append(
                    f"{model} complete attempt {attempt}/{attempts}: "
                    f"{safe_error_message(error)}"
                )
                if _is_non_retryable_http_error(error):
                    return None, best_partial, errors
                continue

            if len(draft["tracks"]) >= count:
                return draft, best_partial, errors
            errors.append(
                f"{model} returned {len(draft['tracks'])} of {count} unique tracks"
            )
            if best_partial is None or len(draft["tracks"]) > len(best_partial["tracks"]):
                best_partial = draft

            missing = count - len(draft["tracks"])
            if 0 < missing <= _batch_size(config.provider, count):
                return None, draft, errors
    return None, best_partial, errors


async def _complete_in_batches(
    client: httpx.AsyncClient,
    config: AppConfig,
    prompt: str,
    count: int,
    *,
    initial_draft: dict[str, Any] | None = None,
    previous_errors: list[str] | None = None,
) -> dict[str, Any]:
    tracks = _unique_tracks((initial_draft or {}).get("tracks", []), limit=count)
    seen = {_candidate_key(track) for track in tracks}
    title = str((initial_draft or {}).get("title", "")).strip()
    description = str((initial_draft or {}).get("description", "")).strip()
    errors = list(previous_errors or [])
    batch_size = _batch_size(config.provider, count)
    remaining_at_start = max(0, count - len(tracks))
    max_batches = min(20, max(3, math.ceil(max(1, remaining_at_start) / batch_size) * 3))
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
                except Exception as error:
                    errors.append(
                        f"{model} batch {batch_number} attempt {attempt}/{attempts}: "
                        f"{safe_error_message(error)}"
                    )
                    if _is_non_retryable_http_error(error):
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
        rate_limit_message = _rate_limit_exhausted_message(config)
        if rate_limit_message is not None:
            raise ValueError(rate_limit_message)
        last_error = errors[-1] if errors else "No additional valid tracks were returned."
        raise ValueError(
            f"The AI provider produced {len(tracks)} of {count} unique tracks. "
            f"{safe_error_message(ValueError(last_error))}"
        )
    return {"title": title, "description": description, "tracks": tracks[:count]}


def _rate_limit_exhausted_message(config: AppConfig) -> str | None:
    """Return a clear "come back in Xs" message if every model in the chain is
    currently rate-limited, or None if at least one is still available to try."""
    cooldown = longest_remaining_cooldown(config.provider, config.model_chain)
    if cooldown is None:
        return None
    fallback_count = len(config.model_chain) - 1
    chain_desc = (
        "the selected model"
        if fallback_count <= 0
        else f"the selected model and its {fallback_count} fallback"
        f"{'s' if fallback_count > 1 else ''}"
    )
    return (
        f"Rate limit reached on {chain_desc}. Try again in {format_cooldown(cooldown)}."
    )


async def generate_playlist_draft(
    config: AppConfig, prompt: str, count: int
) -> dict[str, Any]:
    """Try one complete response first, then batch only the missing tracks."""
    if not config.configured:
        raise ValueError("Configure a valid AI provider and API key before generating a playlist.")
    rate_limit_message = _rate_limit_exhausted_message(config)
    if rate_limit_message is not None:
        raise ValueError(rate_limit_message)
    timeout = httpx.Timeout(150.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        complete, best_partial, errors = await _try_complete_request(
            client, config, prompt, count
        )
        if complete is not None:
            return complete
        return await _complete_in_batches(
            client,
            config,
            prompt,
            count,
            initial_draft=best_partial,
            previous_errors=errors,
        )
