"""Non-destructive AI refinement for saved draft playlists."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.config import load_config
from backend.constraint_interpreter import interpret_constraints
from backend.generation_runtime import resolve_candidates
from backend.llm import generate_playlist_draft, safe_error_message
from backend.metadata_validation import (
    MetadataConstraints,
    activate_constraints,
    active_constraints,
    constraints_from_payload,
    validate_candidate,
)
from backend.playlist_library import (
    PlaylistNotFoundError,
    PlaylistWriteRequest,
    get_library,
)
from backend.prompt_validation import assess_interpretation
from backend.text_normalization import normalize_identity
from backend.youtube import track_identity_key

router = APIRouter(prefix="/library/playlists", tags=["playlist-refinement"])

_ARTIST_SEPARATOR_RE = re.compile(
    r"\s*(?:,|&|\band\b|\be\b|\bfeat\.?\b|\bfeaturing\b|\bwith\b)\s*",
    re.IGNORECASE,
)
_REMOVAL_INTENT_RE = re.compile(
    r"\b(?:"
    r"remove|delete|drop|exclude|without|"
    r"rimuovi|rimuovere|elimina|eliminare|togli|togliere|escludi|escludere|senza|"
    r"elimina|eliminar|quita|quitar|excluye|excluir|sin|"
    r"retire|retirer|supprime|supprimer|exclus|exclure|sans|"
    r"entferne|entfernen|loesche|losche|lösche|ausschliessen|ausschließen|ohne"
    r")\b",
    re.IGNORECASE,
)
_MIN_HARD_CONSTRAINT_CONFIDENCE = 0.85
_MAX_REFINEMENT_ATTEMPTS = 2


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


@dataclass(slots=True)
class _RefinementConstraints:
    metadata: MetadataConstraints
    excluded_tracks: tuple[dict[str, str], ...] = ()

    @property
    def active(self) -> bool:
        return self.metadata.active or bool(self.excluded_tracks)


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


def _artist_identity_keys(value: str) -> set[str]:
    normalized = " ".join(str(value).split()).strip()
    if not normalized:
        return set()
    keys = {normalize_identity(normalized)}
    for part in _ARTIST_SEPARATOR_RE.split(normalized):
        key = normalize_identity(part)
        if key:
            keys.add(key)
    return keys


def _contains_identity(text: str, identity: str) -> bool:
    """Match a normalized entity as whole tokens, not inside another word."""
    if not text or not identity:
        return False
    return f" {identity} " in f" {text} "


def _current_artist_names(tracks: list[dict[str, Any]]) -> list[str]:
    """Return unique canonical artist names occurring in the current playlist."""
    names: list[str] = []
    seen: set[str] = set()
    for track in tracks:
        raw = str(track.get("artists") or track.get("artist") or "").strip()
        for part in _ARTIST_SEPARATOR_RE.split(raw):
            name = " ".join(part.split()).strip()
            key = normalize_identity(name)
            if name and key and key not in seen:
                seen.add(key)
                names.append(name)
    return names


def _local_explicit_removals(
    instruction: str,
    current_tracks: list[dict[str, Any]],
) -> _RefinementConstraints:
    """Resolve simple removals only against entities already present in the draft.

    Without an explicit removal/exclusion verb this returns no hard constraints, and it never
    invents an artist or track that is not already present in the current playlist.
    """
    if not _REMOVAL_INTENT_RE.search(instruction):
        return _RefinementConstraints(MetadataConstraints())

    normalized_instruction = normalize_identity(instruction)
    artist_names = _current_artist_names(current_tracks)
    artist_keys = {name: normalize_identity(name) for name in artist_names}

    surname_owners: dict[str, list[str]] = {}
    for name, key in artist_keys.items():
        tokens = key.split()
        if len(tokens) >= 2:
            surname = tokens[-1]
            if len(surname) >= 4:
                surname_owners.setdefault(surname, []).append(name)

    excluded_artists: list[str] = []
    excluded_artist_keys: set[str] = set()
    for name, key in artist_keys.items():
        matched = _contains_identity(normalized_instruction, key)
        if not matched:
            tokens = key.split()
            surname = tokens[-1] if len(tokens) >= 2 else ""
            matched = bool(
                surname
                and len(surname_owners.get(surname, [])) == 1
                and _contains_identity(normalized_instruction, surname)
            )
        if matched and key not in excluded_artist_keys:
            excluded_artists.append(name)
            excluded_artist_keys.add(key)

    title_owners: dict[str, list[dict[str, Any]]] = {}
    for track in current_tracks:
        title_key = normalize_identity(str(track.get("title") or ""))
        if len(title_key) >= 3:
            title_owners.setdefault(title_key, []).append(track)

    excluded_tracks: list[dict[str, str]] = []
    for title_key, owners in title_owners.items():
        if len(owners) != 1 or not _contains_identity(normalized_instruction, title_key):
            continue
        track = owners[0]
        artist = str(track.get("artists") or track.get("artist") or "").strip()
        if any(key in excluded_artist_keys for key in _artist_identity_keys(artist)):
            continue
        excluded_tracks.append(
            {
                "artist": artist[:180],
                "title": str(track.get("title") or "").strip()[:220],
            }
        )

    return _RefinementConstraints(
        metadata=MetadataConstraints(excluded_artists=excluded_artists),
        excluded_tracks=tuple(excluded_tracks[:20]),
    )


def _clean_excluded_tracks(payload: dict[str, Any]) -> tuple[dict[str, str], ...]:
    confidence = payload.get("field_confidence")
    if isinstance(confidence, dict):
        try:
            trusted = (
                float(confidence.get("excluded_tracks", 0.0))
                >= _MIN_HARD_CONSTRAINT_CONFIDENCE
            )
        except (TypeError, ValueError):
            trusted = False
    else:
        trusted = str(payload.get("confidence", "")).casefold() == "high"
    if not trusted:
        return ()

    raw = payload.get("excluded_tracks")
    if not isinstance(raw, list):
        return ()
    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in raw:
        if not isinstance(value, dict):
            continue
        artist = " ".join(str(value.get("artist") or "").split()).strip()
        title = " ".join(str(value.get("title") or "").split()).strip()
        if not artist or not title:
            continue
        key = track_identity_key(title, artist)
        if key and key not in seen:
            seen.add(key)
            cleaned.append({"artist": artist[:180], "title": title[:220]})
    return tuple(cleaned[:20])


def _merge_refinement_constraints(
    interpreted: _RefinementConstraints,
    local: _RefinementConstraints,
) -> _RefinementConstraints:
    """Merge trusted AI interpretation with deterministic current-playlist removals."""
    ai = interpreted.metadata

    excluded_artists: list[str] = []
    seen_artists: set[str] = set()
    for artist in [*ai.excluded_artists, *local.metadata.excluded_artists]:
        key = normalize_identity(artist)
        if key and key not in seen_artists:
            seen_artists.add(key)
            excluded_artists.append(artist)

    excluded_tracks: list[dict[str, str]] = []
    seen_tracks: set[str] = set()
    for track in [*interpreted.excluded_tracks, *local.excluded_tracks]:
        key = track_identity_key(track["title"], track["artist"])
        if key and key not in seen_tracks:
            seen_tracks.add(key)
            excluded_tracks.append(track)

    return _RefinementConstraints(
        metadata=MetadataConstraints(
            release_year=ai.release_year,
            release_year_from=ai.release_year_from,
            release_year_to=ai.release_year_to,
            artist_country=ai.artist_country,
            allowed_artists=list(ai.allowed_artists),
            excluded_artists=excluded_artists,
            allowed_albums=list(ai.allowed_albums),
            excluded_albums=list(ai.excluded_albums),
            exception_tracks=list(ai.exception_tracks),
            contradictions=list(ai.contradictions),
            field_confidence=dict(ai.field_confidence),
        ),
        excluded_tracks=tuple(excluded_tracks[:20]),
    )


async def _interpret_refinement_constraints(
    config: Any,
    instruction: str,
    current_tracks: list[dict[str, Any]] | None = None,
) -> _RefinementConstraints:
    """Extract hard constraints without making interpretation mandatory for refinement."""
    local = _local_explicit_removals(instruction, current_tracks or [])
    payload = await interpret_constraints(config, instruction)
    if not isinstance(payload, dict):
        return local

    assessment = assess_interpretation(payload)
    if assessment.status != "valid":
        # Preview is non-destructive. Keep only locally provable removals when the hard-
        # constraint interpreter is uncertain, and let the refinement model handle the prose.
        return local

    interpreted = _RefinementConstraints(
        metadata=constraints_from_payload(payload),
        excluded_tracks=_clean_excluded_tracks(payload),
    )
    return _merge_refinement_constraints(interpreted, local)


def _direct_constraint_violation(
    track: dict[str, Any],
    constraints: _RefinementConstraints,
) -> str | None:
    artist_text = str(track.get("artists") or track.get("artist") or "").strip()
    artist_keys = _artist_identity_keys(artist_text)
    excluded_artist_keys = {
        normalize_identity(artist)
        for artist in constraints.metadata.excluded_artists
        if normalize_identity(artist)
    }
    if artist_keys & excluded_artist_keys:
        return f"excluded artist: {artist_text}"

    allowed_artist_keys = {
        normalize_identity(artist)
        for artist in constraints.metadata.allowed_artists
        if normalize_identity(artist)
    }
    if allowed_artist_keys and not (artist_keys & allowed_artist_keys):
        return f"artist outside the allowed set: {artist_text}"

    key = _track_key(track)
    if key and any(
        key == track_identity_key(item["title"], item["artist"])
        for item in constraints.excluded_tracks
    ):
        return f"excluded track: {artist_text} — {track.get('title', '')}"
    return None


def _metadata_requires_lookup(constraints: MetadataConstraints) -> bool:
    return any(
        (
            constraints.release_year is not None,
            constraints.release_year_from is not None,
            constraints.release_year_to is not None,
            constraints.artist_country is not None,
            bool(constraints.allowed_albums),
            bool(constraints.excluded_albums),
        )
    )


async def _eligible_existing_tracks(
    tracks: list[dict[str, Any]],
    constraints: _RefinementConstraints,
) -> list[dict[str, Any]]:
    eligible: list[dict[str, Any]] = []
    needs_metadata = _metadata_requires_lookup(constraints.metadata)
    for track in tracks:
        if _direct_constraint_violation(track, constraints):
            continue
        if needs_metadata:
            validation = await validate_candidate(track, constraints.metadata)
            if validation.status != "valid":
                continue
        eligible.append(track)
    return eligible


def _constraint_guidance(constraints: _RefinementConstraints) -> str:
    lines: list[str] = []
    metadata = constraints.metadata
    if metadata.allowed_artists:
        lines.append("Allowed artists only: " + ", ".join(metadata.allowed_artists))
    if metadata.excluded_artists:
        lines.append("Excluded artists: " + ", ".join(metadata.excluded_artists))
    if metadata.allowed_albums:
        lines.append("Allowed albums only: " + ", ".join(metadata.allowed_albums))
    if metadata.excluded_albums:
        lines.append("Excluded albums: " + ", ".join(metadata.excluded_albums))
    if metadata.release_year is not None:
        lines.append(f"Release year must be {metadata.release_year}")
    if metadata.release_year_from is not None:
        lines.append(f"Release year must be >= {metadata.release_year_from}")
    if metadata.release_year_to is not None:
        lines.append(f"Release year must be <= {metadata.release_year_to}")
    for track in constraints.excluded_tracks:
        lines.append(f"Excluded track: {track['artist']} — {track['title']}")
    return "\n".join(f"- {line}" for line in lines) or "- None"


def _refinement_prompt(
    record: dict[str, Any],
    instruction: str,
    constraints: _RefinementConstraints,
    *,
    retry: bool = False,
) -> str:
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
    retry_note = (
        "\nThe previous refinement attempt did not produce a complete catalogue-resolvable "
        "playlist satisfying every hard constraint. Use different replacement songs and "
        "do not reintroduce any forbidden artist or track.\n"
        if retry
        else ""
    )

    return (
        "Refine this existing playlist instead of creating an unrelated replacement.\n\n"
        f"Original request:\n{original_prompt or 'No original request is available.'}\n\n"
        f"Previously applied refinements:\n{previous_text}\n\n"
        f"New refinement instruction:\n{instruction}\n\n"
        "The following hard constraints were extracted from the NEW refinement instruction. "
        "They are mandatory and override stylistic preferences when they conflict:\n"
        f"{_constraint_guidance(constraints)}\n\n"
        f"Current playlist ({count} tracks):\n{current}\n\n"
        f"Return exactly {count} tracks. Keep every current track that still fits the new "
        "instruction; do not replace songs merely for novelty. Reorder existing tracks when "
        "that is enough to satisfy the instruction. Replace every current track that violates "
        "a hard constraint, and never return an excluded artist or excluded track. Replace only "
        "the other tracks that genuinely need to change. Previously applied refinements remain "
        "in force unless the new instruction explicitly supersedes them. The new instruction "
        "may refine or supersede preferences from the original request when it explicitly says "
        "so. Never duplicate a song. Use canonical released artist and track names."
        f"{retry_note}"
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
    eligible_current_tracks: list[dict[str, Any]],
    generated_tracks: list[dict[str, Any]],
    resolved_new_tracks: list[dict[str, Any]],
    constraints: _RefinementConstraints | None = None,
    *,
    target_count: int | None = None,
) -> list[dict[str, Any]]:
    """Preserve compliant resolved tracks and never reinsert hard-constraint violations."""
    hard = constraints or _RefinementConstraints(MetadataConstraints())
    target = target_count if target_count is not None else len(eligible_current_tracks)
    current_by_key = {
        _track_key(track): track
        for track in eligible_current_tracks
        if _track_key(track) and not _direct_constraint_violation(track, hard)
    }
    resolved_by_key = {
        _track_key(track): track
        for track in resolved_new_tracks
        if _track_key(track) and not _direct_constraint_violation(track, hard)
    }

    selected: list[dict[str, Any]] = []
    selected_keys: set[str] = set()
    selected_video_ids: set[str] = set()

    def append(track: dict[str, Any]) -> bool:
        if _direct_constraint_violation(track, hard):
            return False
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
        if not key or _direct_constraint_violation(generated, hard):
            continue
        existing = current_by_key.get(key)
        if existing is not None:
            append(_merge_track_metadata(existing, generated))
            continue
        resolved = resolved_by_key.get(key)
        if resolved is not None:
            append(_merge_track_metadata(resolved, generated))

    for existing in eligible_current_tracks:
        if len(selected) >= target:
            break
        append(dict(existing))

    return selected[:target]


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


def _validate_direct_constraints(
    tracks: list[dict[str, Any]],
    constraints: _RefinementConstraints,
) -> None:
    violations = [
        violation
        for track in tracks
        if (violation := _direct_constraint_violation(track, constraints))
    ]
    if violations:
        raise ValueError(
            "The refinement preview still violates an explicit instruction: "
            + "; ".join(dict.fromkeys(violations))
        )


async def _build_preview(record: dict[str, Any], instruction: str) -> dict[str, Any]:
    playlist = record["playlist"]
    current_tracks = [
        dict(track) for track in playlist.get("tracks", []) if isinstance(track, dict)
    ]
    if not current_tracks:
        raise ValueError("The draft contains no tracks to refine.")
    if len(current_tracks) > 100:
        raise ValueError("Refinement currently supports playlists of up to 100 tracks.")

    config = load_config()
    constraints = await _interpret_refinement_constraints(
        config,
        instruction,
        current_tracks,
    )
    eligible_current = await _eligible_existing_tracks(current_tracks, constraints)
    target_count = len(current_tracks)
    unresolved: list[dict[str, Any]] = []
    refined_tracks: list[dict[str, Any]] = []

    for attempt in range(_MAX_REFINEMENT_ATTEMPTS):
        draft = await generate_playlist_draft(
            config,
            _refinement_prompt(record, instruction, constraints, retry=attempt > 0),
            target_count,
        )
        generated_tracks = [
            dict(track)
            for track in draft.get("tracks", [])
            if isinstance(track, dict)
            and not _direct_constraint_violation(track, constraints)
        ]
        eligible_keys = {_track_key(track) for track in eligible_current}
        new_candidates = [
            track for track in generated_tracks if _track_key(track) not in eligible_keys
        ]

        previous_constraints = active_constraints()
        activate_constraints(constraints.metadata)
        try:
            resolved_new, unresolved = await resolve_candidates(
                new_candidates,
                _generation_options(record).model_dump(),
            )
        finally:
            activate_constraints(previous_constraints)

        resolved_new = [
            track
            for track in resolved_new
            if not _direct_constraint_violation(track, constraints)
        ]
        refined_tracks = _assemble_refined_tracks(
            eligible_current,
            generated_tracks,
            resolved_new,
            constraints,
            target_count=target_count,
        )
        if len(refined_tracks) == target_count:
            _validate_direct_constraints(refined_tracks, constraints)
            break
    else:
        raise ValueError(
            "PlaylistMuse could not produce a complete refinement that satisfies every explicit "
            "constraint. Try a slightly broader refinement instruction."
        )

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

    try:
        source_tracks = [
            dict(track)
            for track in record["playlist"].get("tracks", [])
            if isinstance(track, dict)
        ]
        constraints = await _interpret_refinement_constraints(
            load_config(),
            request.instruction,
            source_tracks,
        )
        preview_tracks = [
            dict(track) for track in playlist.get("tracks", []) if isinstance(track, dict)
        ]
        _validate_direct_constraints(preview_tracks, constraints)
        expected_count = int(record.get("track_count") or len(source_tracks))
        if len(preview_tracks) != expected_count:
            raise ValueError("The refinement preview no longer has the expected number of tracks.")
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
