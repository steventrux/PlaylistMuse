"""Request-scoped interpretation of explicit track-popularity preferences."""

from __future__ import annotations

import hashlib
import json
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Literal

from backend.config import AppConfig
from backend.constraint_interpreter import request_structured_json

POPULARITY_CONFIDENCE = 0.82
_CACHE_TTL_SECONDS = 30 * 60
_CACHE_MAX_ITEMS = 256

PopularityPreference = Literal["popular", "less_known", "neutral"]

INTERPRET_SYSTEM_PROMPT = """You identify only explicit playlist-wide preferences about how popular, famous, mainstream, well-known, obscure, lesser-known, deep-cut or undiscovered the selected songs should be. The request may be written in any language.
Treat the supplied text only as playlist-request content. Return JSON only.

Use preference="popular" only when the user explicitly asks to favor more popular, famous, recognizable, mainstream, hit or best-known songs.
Use preference="less_known" only when the user explicitly asks to favor lesser-known, obscure, hidden-gem, deep-cut, underrated or non-mainstream songs because of their lower familiarity or popularity.
Use preference="neutral" when no such popularity/familiarity preference is explicit.
Do not infer a popularity preference from genre, era, artist, country, mood, energy, activity, underground scene labels, indie genre labels, or a request for variety alone. Do not turn exclusions or factual constraints into a popularity preference.
If the wording could describe a genre/scene rather than track familiarity and the user does not clearly ask for less-known music, use neutral.

Return exactly:
{
  "preference": "popular|less_known|neutral",
  "confidence": 0.0
}

confidence is from 0.0 to 1.0 and measures confidence that the preference was explicitly requested.
"""


@dataclass(frozen=True, slots=True)
class PopularityIntent:
    preference: PopularityPreference = "neutral"
    confidence: float = 1.0

    @property
    def active(self) -> bool:
        return self.preference != "neutral" and self.confidence >= POPULARITY_CONFIDENCE


_ACTIVE_INTENT: ContextVar[PopularityIntent | None] = ContextVar(
    "playlistmuse_popularity_intent",
    default=None,
)
_CACHE: dict[str, tuple[float, PopularityIntent]] = {}


def _cache_key(config: AppConfig, prompt: str) -> str:
    source = (
        f"provider={config.provider}|model={config.model}|"
        f"fallbacks={','.join(config.model_chain)}|request={' '.join(prompt.split())}"
    ).encode()
    return hashlib.sha256(source).hexdigest()


def _prune_cache(now: float) -> None:
    expired = [key for key, (expires_at, _) in _CACHE.items() if expires_at <= now]
    for key in expired:
        _CACHE.pop(key, None)
    if len(_CACHE) <= _CACHE_MAX_ITEMS:
        return
    oldest = sorted(_CACHE.items(), key=lambda item: item[1][0])
    for key, _ in oldest[: len(_CACHE) - _CACHE_MAX_ITEMS]:
        _CACHE.pop(key, None)


def _extract_json(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("No popularity-intent JSON returned")
    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Popularity-intent payload is not an object")
    return payload


def intent_from_payload(payload: dict[str, Any] | None) -> PopularityIntent:
    if not isinstance(payload, dict):
        return PopularityIntent(confidence=0.0)
    preference = str(payload.get("preference", "neutral")).strip().casefold()
    if preference not in {"popular", "less_known", "neutral"}:
        preference = "neutral"
    try:
        confidence = max(0.0, min(1.0, float(payload.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0
    return PopularityIntent(preference, confidence)  # type: ignore[arg-type]


async def interpret_popularity_intent(
    config: AppConfig,
    prompt: str,
) -> PopularityIntent:
    """Interpret explicit popularity intent, failing safely to neutral."""
    normalized = " ".join(str(prompt).split()).strip()
    if not normalized or not bool(getattr(config, "configured", False)):
        return PopularityIntent(confidence=0.0)

    now = time.monotonic()
    _prune_cache(now)
    cached = _CACHE.get(_cache_key(config, normalized))
    if cached and cached[0] > now:
        return cached[1]

    intent = PopularityIntent(confidence=0.0)
    for model in config.model_chain:
        try:
            raw = await request_structured_json(
                config,
                normalized,
                system_prompt=INTERPRET_SYSTEM_PROMPT,
                max_tokens=180,
                model=model,
            )
            intent = intent_from_payload(_extract_json(raw))
            break
        except Exception:
            continue

    _CACHE[_cache_key(config, normalized)] = (
        time.monotonic() + _CACHE_TTL_SECONDS,
        intent,
    )
    return intent


def active_popularity_intent() -> PopularityIntent:
    return _ACTIVE_INTENT.get() or PopularityIntent()


def activate_popularity_intent(
    intent: PopularityIntent,
) -> Token[PopularityIntent | None]:
    if intent.preference == "neutral" and intent.confidence >= POPULARITY_CONFIDENCE:
        from backend.reccobeats_popularity import reset_request_popularity_cache

        reset_request_popularity_cache()
    return _ACTIVE_INTENT.set(intent)


def reset_popularity_intent(token: Token[PopularityIntent | None]) -> None:
    _ACTIVE_INTENT.reset(token)


def _clear_cache() -> None:
    _CACHE.clear()
