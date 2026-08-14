"""LLM curation over immutable ReccoBeats identities for explicit popularity requests."""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.config import AppConfig
from backend.constraint_interpreter import request_structured_json
from backend.popularity_policy import popularity_policy_label

LOGGER = logging.getLogger("playlistmuse.performance")
SELECTOR_BATCH_SIZE = 10

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


def _error_status(error: Exception) -> int | None:
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    return int(status) if isinstance(status, int) else None


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


def _candidate_lines(candidates: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for index, candidate in enumerate(candidates, start=1):
        artist = " ".join(str(candidate.get("artist", "")).split()).strip()
        title = " ".join(str(candidate.get("title", "")).split()).strip()
        score = candidate.get("popularity")
        if artist and title:
            lines.append(f"{index}. {artist} — {title} [popularity={score}]")
    return lines


def _selection_request(
    prompt: str,
    candidates: list[dict[str, Any]],
    *,
    count: int,
    preference: str,
) -> str:
    return (
        f"{prompt}\n\n"
        "INTERNAL IMMUTABLE RECCOBEATS CANDIDATES\n"
        f"Explicit popularity policy: {preference} {popularity_policy_label(preference)}.\n"
        f"Select at most {min(count, len(candidates))} suitable indices.\n"
        + "\n".join(_candidate_lines(candidates))
    )


async def _select_once(
    config: AppConfig,
    prompt: str,
    candidates: list[dict[str, Any]],
    *,
    count: int,
    preference: str,
    mode: str,
) -> dict[str, Any] | None:
    request = _selection_request(
        prompt,
        candidates,
        count=count,
        preference=preference,
    )
    for model in config.model_chain:
        try:
            raw = await request_structured_json(
                config,
                request,
                system_prompt=SYSTEM_PROMPT,
                max_tokens=min(8_000, max(2_000, count * 260)),
                model=model,
            )
            draft = draft_from_selection_payload(
                _extract_json(raw),
                candidates,
                limit=min(count, len(candidates)),
            )
            if draft is not None:
                LOGGER.info(
                    "reccobeats_selector mode=%s model=%s candidates=%s selected=%s outcome=success",
                    mode,
                    model,
                    len(candidates),
                    len(draft.get("tracks", [])),
                )
                return draft
            LOGGER.info(
                "reccobeats_selector mode=%s model=%s candidates=%s selected=0 outcome=empty",
                mode,
                model,
                len(candidates),
            )
        except Exception as error:  # noqa: BLE001 - selector is optional and has fallbacks.
            LOGGER.info(
                "reccobeats_selector mode=%s model=%s candidates=%s outcome=error error=%s status=%s",
                mode,
                model,
                len(candidates),
                type(error).__name__,
                _error_status(error) if _error_status(error) is not None else "n/a",
            )
    return None


def _merge_selector_drafts(
    drafts: list[dict[str, Any]],
    *,
    limit: int,
) -> dict[str, Any] | None:
    tracks: list[dict[str, Any]] = []
    seen: set[str] = set()
    title = ""
    description = ""
    for draft in drafts:
        title = title or str(draft.get("title", "")).strip()
        description = description or str(draft.get("description", "")).strip()
        for track in draft.get("tracks", []):
            if not isinstance(track, dict):
                continue
            recco_id = str(track.get("reccobeats_id", "")).strip()
            identity = "|".join(
                [
                    str(track.get("artist", "")).strip().casefold(),
                    str(track.get("title", "")).strip().casefold(),
                ]
            )
            key = recco_id or identity
            if not key or key in seen:
                continue
            seen.add(key)
            tracks.append(dict(track))
            if len(tracks) >= limit:
                break
        if len(tracks) >= limit:
            break
    if not tracks:
        return None
    return {"title": title, "description": description, "tracks": tracks}


def deterministic_reccobeats_draft(
    candidates: list[dict[str, Any]],
    *,
    count: int,
) -> dict[str, Any] | None:
    """Preserve valid Recco identities if the optional selector LLM is unavailable."""
    if not candidates or count <= 0:
        return None
    tracks: list[dict[str, Any]] = []
    for candidate in candidates[:count]:
        track = dict(candidate)
        track.setdefault("description", "Catalogue-backed track.")
        track.setdefault(
            "reason",
            "Selected from the verified candidate pool for this playlist request.",
        )
        tracks.append(track)
    return {"title": "", "description": "", "tracks": tracks} if tracks else None


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
    usable = [dict(candidate) for candidate in candidates if _candidate_lines([candidate])]
    if not usable:
        return None

    full = await _select_once(
        config,
        prompt,
        usable,
        count=count,
        preference=preference,
        mode="full",
    )
    if full is not None:
        return full

    drafts: list[dict[str, Any]] = []
    remaining = min(count, len(usable))
    for start in range(0, len(usable), SELECTOR_BATCH_SIZE):
        if remaining <= 0:
            break
        batch = usable[start : start + SELECTOR_BATCH_SIZE]
        draft = await _select_once(
            config,
            prompt,
            batch,
            count=min(remaining, len(batch)),
            preference=preference,
            mode="batch",
        )
        if draft is None:
            continue
        drafts.append(draft)
        remaining -= len(draft.get("tracks", []))

    merged = _merge_selector_drafts(drafts, limit=min(count, len(usable)))
    if merged is not None:
        LOGGER.info(
            "reccobeats_selector mode=batched candidates=%s selected=%s outcome=success",
            len(usable),
            len(merged.get("tracks", [])),
        )
        return merged

    fallback = deterministic_reccobeats_draft(usable, count=min(count, len(usable)))
    LOGGER.info(
        "reccobeats_selector mode=deterministic candidates=%s selected=%s outcome=fallback",
        len(usable),
        len((fallback or {}).get("tracks", [])),
    )
    return fallback
