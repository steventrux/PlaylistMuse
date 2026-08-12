"""Targeted Playlist Studio refinements built on the existing refinement engine."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.artist_quota_detection import (
    ArtistMinimumQuota,
    extract_artist_minimum_quotas,
    quota_deficits,
    quota_guidance,
)
from backend.config import load_config
from backend.llm import safe_error_message
from backend.playlist_library import (
    PlaylistNotFoundError,
    PlaylistWriteRequest,
    get_library,
)
from backend.playlist_refinement import (
    _addition_mismatches_or_error,
    _build_preview,
    _generation_options,
    _interpret_refinement_constraints,
    _record_or_404,
    _refinement_summary,
    _require_draft,
    _track_key,
    _validate_direct_constraints,
)
from backend.recording_variants import (
    RecordingVariantPolicy,
    activate_recording_policy,
    interpret_recording_policy,
    recording_policy_guidance,
    recording_variant_violations,
    reset_recording_policy,
    track_matches_variant,
)
from backend.refinement_intent import (
    studio_addition_guidance,
    studio_artist_addition_targets,
)
from backend.refinement_targets import (
    ArtistAdditionTarget,
    format_artist_addition_mismatches,
    repair_artist_addition_targets,
)

router = APIRouter(prefix="/library/playlists", tags=["playlist-studio"])


class StudioRefinementInstruction(BaseModel):
    """One refinement instruction plus the Playlist Studio editing scope."""

    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(min_length=3, max_length=1000)
    target_positions: list[int] = Field(default_factory=list, max_length=100)
    locked_positions: list[int] = Field(default_factory=list, max_length=100)

    @field_validator("instruction")
    @classmethod
    def normalize_instruction(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("target_positions", "locked_positions")
    @classmethod
    def normalize_positions(cls, value: list[int]) -> list[int]:
        normalized = sorted(set(value))
        if any(position < 1 or position > 100 for position in normalized):
            raise ValueError("Track positions must be between 1 and 100.")
        return normalized


class ApplyStudioRefinementRequest(StudioRefinementInstruction):
    """Confirmed Playlist Studio preview that should replace the current draft."""

    playlist: dict[str, Any]


def _playlist_tracks(record: dict[str, Any]) -> list[dict[str, Any]]:
    playlist = record.get("playlist")
    if not isinstance(playlist, dict):
        return []
    return [dict(track) for track in playlist.get("tracks", []) if isinstance(track, dict)]


def _resolve_scope(
    track_count: int,
    target_positions: list[int],
    locked_positions: list[int],
) -> tuple[list[int], list[int]]:
    if track_count <= 0:
        raise ValueError("The draft contains no tracks to refine.")

    for position in [*target_positions, *locked_positions]:
        if position > track_count:
            raise ValueError(
                f"Track position {position} is outside this {track_count}-track playlist."
            )

    locked = set(locked_positions)
    targets = set(target_positions) if target_positions else set(range(1, track_count + 1))
    editable = sorted(targets - locked)
    if not editable:
        raise ValueError("Select at least one unlocked track for Playlist Studio.")
    return editable, sorted(locked)


def _record_prompt(record: dict[str, Any]) -> str:
    playlist = record.get("playlist")
    if isinstance(playlist, dict):
        prompt = str(playlist.get("prompt") or "").strip()
        if prompt:
            return prompt
    return str(record.get("prompt") or "").strip()


async def _effective_recording_policy(
    record: dict[str, Any],
    instruction: str,
) -> RecordingVariantPolicy:
    """Keep original recording constraints unless the new instruction supersedes them."""
    config = load_config()
    refinement_policy = await interpret_recording_policy(config, instruction)
    if refinement_policy.active:
        return refinement_policy.for_refinement()

    original_prompt = _record_prompt(record)
    if not original_prompt:
        return refinement_policy.for_refinement()
    original_policy = await interpret_recording_policy(config, original_prompt)
    return original_policy.for_refinement()


def _reserved_prompt(record: dict[str, Any], editable_positions: list[int]) -> str:
    """Keep non-editable songs visible to the model only as a duplicate-avoidance reserve."""
    playlist = record.get("playlist")
    if not isinstance(playlist, dict):
        return ""
    original_prompt = str(playlist.get("prompt") or record.get("prompt") or "").strip()
    tracks = _playlist_tracks(record)
    editable = set(editable_positions)
    reserved = [
        track
        for position, track in enumerate(tracks, start=1)
        if position not in editable
    ]
    if not reserved:
        return original_prompt

    lines = "\n".join(
        f"- {track.get('artists') or track.get('artist') or 'Unknown artist'} — "
        f"{track.get('title') or 'Unknown track'}"
        for track in reserved
    )
    return (
        f"{original_prompt}\n\n"
        "Playlist Studio reserve: the songs below belong to protected positions outside the "
        "current editing scope. Do not return any of them in the editable slots, because the "
        "final playlist must not contain duplicates:\n"
        f"{lines}"
    ).strip()


def _scoped_record(
    record: dict[str, Any],
    editable_positions: list[int],
) -> dict[str, Any]:
    """Create an in-memory view containing only tracks the AI is allowed to edit."""
    scoped = deepcopy(record)
    source_tracks = _playlist_tracks(record)
    scoped_tracks = [source_tracks[position - 1] for position in editable_positions]
    playlist = scoped.get("playlist")
    if not isinstance(playlist, dict):
        raise ValueError("The saved playlist is invalid.")

    playlist["tracks"] = scoped_tracks
    playlist["requested_count"] = len(scoped_tracks)
    playlist["resolved_count"] = len(scoped_tracks)
    playlist["prompt"] = _reserved_prompt(record, editable_positions)
    scoped["track_count"] = len(scoped_tracks)
    return scoped


def _assert_unique_tracks(tracks: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for track in tracks:
        key = _track_key(track)
        if not key:
            raise ValueError("Playlist Studio returned a track without a usable identity.")
        if key in seen:
            raise ValueError(
                "Playlist Studio produced a duplicate track. Try the preview again."
            )
        seen.add(key)


def _merge_scoped_tracks(
    source_tracks: list[dict[str, Any]],
    scoped_tracks: list[dict[str, Any]],
    editable_positions: list[int],
) -> list[dict[str, Any]]:
    if len(scoped_tracks) != len(editable_positions):
        raise ValueError("Playlist Studio returned an incomplete targeted refinement.")

    merged = [dict(track) for track in source_tracks]
    for position, track in zip(editable_positions, scoped_tracks, strict=True):
        merged[position - 1] = dict(track)
    _assert_unique_tracks(merged)
    return merged


def _assert_immutable_positions(
    source_tracks: list[dict[str, Any]],
    preview_tracks: list[dict[str, Any]],
    editable_positions: list[int],
) -> None:
    editable = set(editable_positions)
    for position, (source, preview) in enumerate(
        zip(source_tracks, preview_tracks, strict=True),
        start=1,
    ):
        if position in editable:
            continue
        if _track_key(source) != _track_key(preview):
            raise ValueError(
                f"Track {position} is outside the Playlist Studio editing scope and cannot change."
            )


def _recording_scope_violations(
    tracks: list[dict[str, Any]],
    policy: RecordingVariantPolicy,
) -> list[str]:
    violations = recording_variant_violations(tracks, policy)
    for variant in sorted(policy.included - policy.required):
        if not any(track_matches_variant(track, variant) for track in tracks):
            violations.append(
                f"the editable selection does not include the requested {variant} version"
            )
    return violations


def _validate_recording_scope(
    tracks: list[dict[str, Any]],
    policy: RecordingVariantPolicy,
) -> None:
    violations = _recording_scope_violations(tracks, policy)
    if violations:
        raise ValueError(
            "Playlist Studio could not satisfy the requested recording-version constraint: "
            + "; ".join(violations[:8])
        )


def _format_artist_quota_deficits(deficits: list[ArtistMinimumQuota]) -> str:
    details = "; ".join(
        f"{quota.artist} still needs {quota.minimum} track(s)" for quota in deficits
    )
    return "Playlist Studio could not satisfy the requested artist quotas: " + details + "."


async def _repair_artist_quota_deficits(
    record: dict[str, Any],
    result: dict[str, Any],
    instruction: str,
    editable_positions: list[int],
    quotas: list[ArtistMinimumQuota],
) -> dict[str, Any]:
    if not quotas:
        return result

    playlist = result.get("playlist")
    if not isinstance(playlist, dict):
        raise ValueError("Playlist Studio returned an invalid preview.")
    preview_tracks = [
        dict(track) for track in playlist.get("tracks", []) if isinstance(track, dict)
    ]
    deficits = quota_deficits(preview_tracks, quotas)
    if not deficits:
        return result
    if sum(deficit.minimum for deficit in deficits) > len(editable_positions):
        raise ValueError(_format_artist_quota_deficits(deficits))

    source_tracks = _playlist_tracks(record)
    source_scope = [source_tracks[position - 1] for position in editable_positions]
    preview_scope = [preview_tracks[position - 1] for position in editable_positions]
    constraints = await _interpret_refinement_constraints(
        load_config(),
        instruction,
        source_scope,
    )
    targets = [
        ArtistAdditionTarget(deficit.artist, deficit.minimum) for deficit in deficits
    ]
    repaired_scope, unresolved = await repair_artist_addition_targets(
        source_scope,
        preview_scope,
        preview_scope,
        targets,
        exclusions=_generation_options(record).model_dump(),
        metadata_constraints=constraints.metadata,
    )
    _validate_direct_constraints(repaired_scope, constraints)
    merged_tracks = _merge_scoped_tracks(
        source_tracks,
        repaired_scope,
        editable_positions,
    )
    remaining = quota_deficits(merged_tracks, quotas)
    if remaining:
        raise ValueError(_format_artist_quota_deficits(remaining))

    playlist["tracks"] = merged_tracks
    playlist["requested_count"] = len(merged_tracks)
    playlist["resolved_count"] = len(merged_tracks)
    existing_unresolved = list(playlist.get("unresolved") or [])
    playlist["unresolved"] = [*existing_unresolved, *unresolved]
    result["summary"] = _refinement_summary(source_tracks, merged_tracks)
    result["summary"]["targeted"] = len(editable_positions)
    studio = result.get("studio")
    if isinstance(studio, dict):
        result["summary"]["locked"] = len(studio.get("locked_positions") or [])
    return result


async def _build_studio_preview_core(
    record: dict[str, Any],
    request: StudioRefinementInstruction,
    instruction: str,
    editable_positions: list[int],
    locked_positions: list[int],
) -> dict[str, Any]:
    source_tracks = _playlist_tracks(record)
    if len(editable_positions) == len(source_tracks):
        result = await _build_preview(record, instruction)
        result["summary"]["targeted"] = len(editable_positions)
        result["summary"]["locked"] = 0
        result["studio"] = {
            "target_positions": [],
            "locked_positions": [],
            "editable_positions": editable_positions,
        }
        return result

    scoped = _scoped_record(record, editable_positions)
    scoped_result = await _build_preview(scoped, instruction)
    scoped_playlist = scoped_result.get("playlist")
    if not isinstance(scoped_playlist, dict):
        raise ValueError("Playlist Studio returned an invalid preview.")
    scoped_tracks = [
        dict(track)
        for track in scoped_playlist.get("tracks", [])
        if isinstance(track, dict)
    ]
    merged_tracks = _merge_scoped_tracks(
        source_tracks,
        scoped_tracks,
        editable_positions,
    )

    playlist = deepcopy(record["playlist"])
    playlist["tracks"] = merged_tracks
    playlist["requested_count"] = len(merged_tracks)
    playlist["resolved_count"] = len(merged_tracks)
    playlist["unresolved"] = list(scoped_playlist.get("unresolved") or [])
    playlist.pop("youtube_playlist", None)
    playlist.pop("lastfm", None)

    summary = _refinement_summary(source_tracks, merged_tracks)
    summary["targeted"] = len(editable_positions)
    summary["locked"] = len(locked_positions)
    return {
        "playlist": playlist,
        "summary": summary,
        "studio": {
            "target_positions": list(request.target_positions),
            "locked_positions": locked_positions,
            "editable_positions": editable_positions,
        },
    }


async def _build_studio_preview(
    record: dict[str, Any],
    request: StudioRefinementInstruction,
) -> dict[str, Any]:
    source_tracks = _playlist_tracks(record)
    editable_positions, locked_positions = _resolve_scope(
        len(source_tracks),
        request.target_positions,
        request.locked_positions,
    )
    policy = await _effective_recording_policy(record, request.instruction)
    quotas = extract_artist_minimum_quotas(request.instruction)
    addition_targets = studio_artist_addition_targets(request.instruction)
    guidance = (
        recording_policy_guidance(policy)
        + quota_guidance(quotas)
        + studio_addition_guidance(addition_targets)
    )
    instruction = f"{request.instruction}{guidance}" if guidance else request.instruction

    token = activate_recording_policy(policy)
    try:
        result = await _build_studio_preview_core(
            record,
            request,
            instruction,
            editable_positions,
            locked_positions,
        )
        result = await _repair_artist_quota_deficits(
            record,
            result,
            request.instruction,
            editable_positions,
            quotas,
        )
    finally:
        reset_recording_policy(token)

    playlist = result.get("playlist")
    if not isinstance(playlist, dict):
        raise ValueError("Playlist Studio returned an invalid preview.")
    preview_tracks = [
        dict(track) for track in playlist.get("tracks", []) if isinstance(track, dict)
    ]
    editable_scope = [preview_tracks[position - 1] for position in editable_positions]
    _validate_recording_scope(editable_scope, policy)
    remaining = quota_deficits(preview_tracks, quotas)
    if remaining:
        raise ValueError(_format_artist_quota_deficits(remaining))
    return result


async def _validate_studio_apply(
    record: dict[str, Any],
    request: ApplyStudioRefinementRequest,
) -> tuple[dict[str, Any], list[int], list[int]]:
    source_tracks = _playlist_tracks(record)
    playlist = deepcopy(request.playlist)
    preview_tracks = [
        dict(track) for track in playlist.get("tracks", []) if isinstance(track, dict)
    ]
    if len(preview_tracks) != len(source_tracks):
        raise ValueError("The Playlist Studio preview no longer matches the saved playlist.")

    editable_positions, locked_positions = _resolve_scope(
        len(source_tracks),
        request.target_positions,
        request.locked_positions,
    )
    _assert_immutable_positions(source_tracks, preview_tracks, editable_positions)
    _assert_unique_tracks(preview_tracks)

    source_scope = [source_tracks[position - 1] for position in editable_positions]
    preview_scope = [preview_tracks[position - 1] for position in editable_positions]
    constraints = await _interpret_refinement_constraints(
        load_config(),
        request.instruction,
        source_scope,
    )
    _validate_direct_constraints(preview_scope, constraints)
    recording_policy = await _effective_recording_policy(record, request.instruction)
    _validate_recording_scope(preview_scope, recording_policy)

    quotas = extract_artist_minimum_quotas(request.instruction)
    remaining = quota_deficits(preview_tracks, quotas)
    if remaining:
        raise ValueError(_format_artist_quota_deficits(remaining))

    addition_targets = studio_artist_addition_targets(request.instruction)
    addition_mismatches = _addition_mismatches_or_error(
        source_scope,
        preview_scope,
        addition_targets,
    )
    if addition_mismatches:
        raise ValueError(format_artist_addition_mismatches(addition_mismatches))

    playlist["name"] = record["playlist"].get("name", record["name"])
    playlist["description"] = record["playlist"].get(
        "description", record["description"]
    )
    playlist["prompt"] = record["playlist"].get("prompt", record["prompt"])
    playlist["tracks"] = preview_tracks
    playlist.pop("youtube_playlist", None)
    playlist.pop("lastfm", None)
    return playlist, editable_positions, locked_positions


@router.post("/{playlist_id}/studio-preview")
async def preview_playlist_studio(
    playlist_id: str,
    request: StudioRefinementInstruction,
) -> dict[str, Any]:
    record = _record_or_404(playlist_id)
    _require_draft(record)
    try:
        return await _build_studio_preview(record, request)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=safe_error_message(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail="Playlist Studio refinement failed. Please try again.",
        ) from error


@router.post("/{playlist_id}/studio-apply")
async def apply_playlist_studio(
    playlist_id: str,
    request: ApplyStudioRefinementRequest,
) -> dict[str, Any]:
    record = _record_or_404(playlist_id)
    _require_draft(record)
    try:
        playlist, editable_positions, locked_positions = await _validate_studio_apply(
            record,
            request,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=safe_error_message(error)) from error

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
            "studio": {
                "target_positions": list(request.target_positions),
                "locked_positions": locked_positions,
                "editable_positions": editable_positions,
            },
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
