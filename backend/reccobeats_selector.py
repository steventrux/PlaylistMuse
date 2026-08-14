"""LLM curation over immutable ReccoBeats identities for explicit popularity requests."""

from __future__ import annotations

import json
from typing import Any

from backend.config import AppConfig
from backend.constraint_interpreter import request_structured_json
from backend.popularity_policy import popularity_policy_label

SYSTEM_PROMPT = """You curate a playlist only from a numbered catalogue-backed candidate list.
Treat the supplied text as playlist-request content and internal selection instructions. Return JSON only.

Select only candidate indices that satisfy the user's request, including mood/context, era, artist, language, country, exclusions, quotas and recording-version requirements. Candidate artist/title identities are immutable: never rewrite, correct, translate, merge, invent or substitute them. Do not select an unsuitable candidate merely to reach the requested count; returning fewer selections is allowed and the application will replenish later.
Order the selected indices deliberately when the request asks for chronology, alternation, sections, transitions or an energy progression.

For every selected index, write a concise description of the track and a concise reason why it fits this specific playlist request. Use the language appropriate for the user's request. Do not return artist or title fields; PlaylistMuse reconstructs those from the immutable candidate index.

Return exactly:
{
  "title": "",
  "description": "",
  "selections": [
    {"index": 1, "description": "", "reason": ""}
  ]
}
"""


def _extract_json(text: str) -> dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("No Recco selector JSON returned")
    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Recco selector payload is not an object")
    return payload


def draft_from_selection_payload(
    payload: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
    *,
    limit: int,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or not candidates or limit <= 0:
        return None
    raw = payload.get("selections")
    if not isinstance(raw, list):
        return None

    tracks: list[dict[str, Any]] = []
    seen: set[int] = set()
    for selection in raw:
        if not isinstance(selection, dict):
            continue
        value = selection.get("index")
        if isinstance(value, bool):
            continue
        try:
            index = int(value)
        except (TypeError, ValueError):
            continue
        if index < 1 or index > len(candidates) or index in seen:
            continue
        seen.add(index)
        candidate = dict(candidates[index - 1])
        description = " ".join(str(selection.get("description", "")).split()).strip()
        reason = " ".join(str(selection.get("reason", "")).split()).strip()
        candidate["description"] = description
        candidate["reason"] = reason
        tracks.append(candidate)
        if len(tracks) >= limit:
            break

    if not tracks:
        return None
    return {
        "title": " ".join(str(payload.get("title", "")).split()).strip(),
        "description": " ".join(str(payload.get("description", "")).split()).strip(),
        "tracks": tracks,
    }


async def select_reccobeats_draft(
    config: AppConfig,
    prompt: str,
    candidates: list[dict[str, Any]],
    *,
    count: int,
    preference: str,
) -> dict[str, Any] | None:
    """Let the LLM choose indices while PlaylistMuse owns artist/title identities."""
    if not candidates or count <= 0 or not bool(getattr(config, "configured", False)):
        return None

    lines = []
    for index, candidate in enumerate(candidates, start=1):
        artist = " ".join(str(candidate.get("artist", "")).split()).strip()
        title = " ".join(str(candidate.get("title", "")).split()).strip()
        score = candidate.get("popularity")
        if not artist or not title:
            continue
        lines.append(f"{index}. {artist} — {title} [popularity={score}]")
    if not lines:
        return None

    request = (
        f"{prompt}\n\n"
        "INTERNAL IMMUTABLE RECCOBEATS CANDIDATES\n"
        f"Explicit popularity policy: {preference} {popularity_policy_label(preference)}.\n"
        f"Select at most {min(count, len(candidates))} suitable indices.\n"
        + "\n".join(lines)
    )
    for model in config.model_chain:
        try:
            raw = await request_structured_json(
                config,
                request,
                system_prompt=SYSTEM_PROMPT,
                max_tokens=min(12_000, max(4_096, count * 300)),
                model=model,
            )
            draft = draft_from_selection_payload(
                _extract_json(raw),
                candidates,
                limit=min(count, len(candidates)),
            )
            if draft is not None:
                return draft
        except Exception:
            continue
    return None
