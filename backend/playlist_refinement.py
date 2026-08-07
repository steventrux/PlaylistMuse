"""Non-destructive AI refinement for saved draft playlists."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.config import load_config
from backend.generation_runtime import resolve_candidates
from backend.llm import generate_playlist_draft, safe_error_message
from backend.playlist_library import (
    PlaylistNotFoundError,
    PlaylistWriteRequest,
    get_library,
)
from backend.youtube import track_identity_key

router = APIRouter(prefix="/library/playlists", tags=["playlist-refinement"])


class RefinementInstruction(BaseModel):
    """One incremental instruction applied to the current draft."""

    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(min_length=3, max_length=1000)

    @field_validator("instruction")
    @classmethod
    def normalize_instruction(cls, value: str) -> str:
        return " ".join(value.split())


class ApplyRefinementRequest(RefinementInstruction):
    """Confirmed preview that should replace the current draft."""

    playlist: dict[str, Any]


class _PlaylistOptions(BaseModel):
    exclude_live: bool = True
    exclude_covers: bool = True
    exclude_remixes: bool = True


def _record_or_404(playlist_id: str) -> dict[str, Any]:
    try:
        return get_library().get(playlist_id)
    except PlaylistNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=f"Playlist {playlist_id} was not found in the local library.",
        ) from error


def _require_draft(record: dict[str, Any]) -> None:
    if record.get("status") != "draft":
        raise HTTPException(
            status_code=409,
            detail="Only draft playlists can be refined.",
        )


def _generation_options(record: dict[str, Any]) -> _PlaylistOptions:
    generation_request = record.get("generation_request")
    if not isinstance(generation_request, dict):
        return _PlaylistOptions()
    options = generation_request.get("options")
    if not isinstance(options, dict):
        return _PlaylistOptions()
    return _PlaylistOptions.model_validate(options)


def _previous_refinement_prompts(record: dict[str, Any]) -> list[str]:
    generation_request = record.get("generation_request")
    if not isinstance(generation_request, dict):
        return []
    refinements = generation_request.get("refinements")
    if not isinstance(refinements, list):
        return []

    prompts: list[str] = []
    for refinement in refinements:
        if isinstance(refinement, str):
            prompt = refinement.strip()
        elif isinstance(refinement, dict):
            prompt = str(refinement.get("prompt") or "").strip()
        else:
            prompt = ""
        if prompt:
            prompts.append(prompt[:1000])
    return prompts[-12:]


def _track_key(track: dict[str, Any]) -> str:
    return track_identity_key(
        str(track.get("title") or ""),
        str(track.get("artists") or track.get("artist") or ""),
    )


def _refinement_prompt(record: dict[str, Any], instruction: str) -> str:
    playlist = record["playlist"]
    tracks = playlist.get("tracks", [])
    current = "\n".join(
        f"{index}. {track.get('artists') or track.get('artist') or 'Unknown artist'} — "
        f"{track.get('title') or 'Unknown track'}"
        for index, track in enumerate(tracks, start=1)
        if isinstance(track, dict)
    )
    previous = _previous_refinement_prompts(record)
    previous_text = "\n".join(f"- {prompt}" for prompt in previous) or "- None"
    original_prompt = str(playlist.get("prompt") or record.get("prompt") or "").strip()
    count = len(tracks)

    return (
        "Refine this existing playlist instead of creating an unrelated replacement.\n\n"
        f"Original request:\n{original_prompt or 'No original request is available.'}\n\n"
        f"Previously applied refinements:\n{previous_text}\n\n"
        f"New refinement instruction:\n{instruction}\n\n"
        f"Current playlist ({count} tracks):\n{current}\n\n"
        f"Return exactly {count} tracks. Keep every current track that still fits the new "
        "instruction; do not replace songs merely for novelty. Reorder existing tracks when "
        "that is enough to satisfy the instruction. Replace only the tracks that need to "
        "change. Previously applied refinements remain in force unless the new instruction "
        "explicitly supersedes them. The new instruction may refine or supersede preferences "
        "from the original request when it explicitly says so. Never duplicate a song. Use "
        "canonical released artist and track names."
    )


def _merge_track_metadata(
    resolved: dict[str, Any],
    generated: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(resolved)
    description = str(generated.get("description") or "").strip()
    reason = str(generated.get("reason") or "").strip()
    if description:
        merged["description"] = description
    if reason:
        merged["reason"] = reason
    return merged


def _assemble_refined_tracks(
    current_tracks: list[dict[str, Any]],
    generated_tracks: list[dict[str, Any]],
    resolved_new_tracks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Preserve existing resolved tracks and resolve only genuinely new selections."""
    current_by_key = {
        _track_key(track): track for track in current_tracks if _track_key(track)
    }
    resolved_by_key = {
        _track_key(track): track for track in resolved_new_tracks if _track_key(track)
    }

    selected: list[dict[str, Any]] = []
    selected_keys: set[str] = set()
    selected_video_ids: set[str] = set()

    def append(track: dict[str, Any]) -> bool:
        key = _track_key(track)
        video_id = str(track.get("video_id") or "").strip()
        if not key or key in selected_keys or (video_id and video_id in selected_video_ids):
            return False
        selected.append(track)
        selected_keys.add(key)
        if video_id:
            selected_video_ids.add(video_id)
        return True

    for generated in generated_tracks:
        key = _track_key(generated)
        if not key:
            continue
        existing = current_by_key.get(key)
        if existing is not None:
            append(_merge_track_metadata(existing, generated))
            continue
        resolved = resolved_by_key.get(key)
        if resolved is not None:
            append(_merge_track_metadata(resolved, generated))

    # If a proposed replacement cannot be resolved, retaining an existing track is safer
    # than silently shrinking the draft or inventing a catalogue match.
    for existing in current_tracks:
        if len(selected) >= len(current_tracks):
            break
        append(dict(existing))

    return selected[: len(current_tracks)]


def _refinement_summary(
    current_tracks: list[dict[str, Any]],
    refined_tracks: list[dict[str, Any]],
) -> dict[str, int]:
    current_positions = {
        _track_key(track): index for index, track in enumerate(current_tracks) if _track_key(track)
    }
    refined_keys = [_track_key(track) for track in refined_tracks]
    kept = sum(1 for key in refined_keys if key in current_positions)
    reordered = sum(
        1
        for index, key in enumerate(refined_keys)
        if key in current_positions and current_positions[key] != index
    )
    return {
        "tracks": len(refined_tracks),
        "kept": kept,
        "changed": max(0, len(refined_tracks) - kept),
        "reordered": reordered,
    }


async def _build_preview(record: dict[str, Any], instruction: str) -> dict[str, Any]:
    playlist = record["playlist"]
    current_tracks = [
        dict(track) for track in playlist.get("tracks", []) if isinstance(track, dict)
    ]
    if not current_tracks:
        raise ValueError("The draft contains no tracks to refine.")
    if len(current_tracks) > 100:
        raise ValueError("Refinement currently supports playlists of up to 100 tracks.")

    draft = await generate_playlist_draft(
        load_config(),
        _refinement_prompt(record, instruction),
        len(current_tracks),
    )
    generated_tracks = [
        dict(track) for track in draft.get("tracks", []) if isinstance(track, dict)
    ]
    current_keys = {_track_key(track) for track in current_tracks}
    new_candidates = [
        track for track in generated_tracks if _track_key(track) not in current_keys
    ]
    resolved_new, unresolved = await resolve_candidates(
        new_candidates,
        _generation_options(record).model_dump(),
    )
    refined_tracks = _assemble_refined_tracks(
        current_tracks,
        generated_tracks,
        resolved_new,
    )
    if len(refined_tracks) != len(current_tracks):
        raise ValueError("PlaylistMuse could not build a complete refinement preview.")

    preview = deepcopy(playlist)
    preview["tracks"] = refined_tracks
    preview["requested_count"] = len(refined_tracks)
    preview["resolved_count"] = len(refined_tracks)
    preview["unresolved"] = unresolved
    preview.pop("youtube_playlist", None)
    preview.pop("lastfm", None)

    return {
        "playlist": preview,
        "summary": _refinement_summary(current_tracks, refined_tracks),
    }


@router.post("/{playlist_id}/refine-preview")
async def refine_playlist_preview(
    playlist_id: str,
    request: RefinementInstruction,
) -> dict[str, Any]:
    record = _record_or_404(playlist_id)
    _require_draft(record)
    try:
        return await _build_preview(record, request.instruction)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=safe_error_message(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail="Playlist refinement failed. Please try again.",
        ) from error


@router.post("/{playlist_id}/refine-apply")
async def apply_playlist_refinement(
    playlist_id: str,
    request: ApplyRefinementRequest,
) -> dict[str, Any]:
    record = _record_or_404(playlist_id)
    _require_draft(record)

    playlist = deepcopy(request.playlist)
    playlist["name"] = record["playlist"].get("name", record["name"])
    playlist["description"] = record["playlist"].get("description", record["description"])
    playlist["prompt"] = record["playlist"].get("prompt", record["prompt"])
    playlist.pop("youtube_playlist", None)

    generation_request = deepcopy(record.get("generation_request"))
    if not isinstance(generation_request, dict):
        generation_request = {}
    refinements = generation_request.get("refinements")
    if not isinstance(refinements, list):
        refinements = []
    refinements.append(
        {
            "prompt": request.instruction,
            "applied_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    )
    generation_request["refinements"] = refinements

    validated = PlaylistWriteRequest.model_validate(
        {
            "playlist": playlist,
            "generation_request": generation_request,
        }
    )
    try:
        return get_library().update(
            playlist_id,
            validated.playlist,
            validated.generation_request,
        )
    except PlaylistNotFoundError as error:
        raise HTTPException(
            status_code=404,
            detail=f"Playlist {playlist_id} was not found in the local library.",
        ) from error
