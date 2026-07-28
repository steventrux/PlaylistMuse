"""PlaylistMuse FastAPI application."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from backend.config import (
    AppConfig,
    api_key_matches_provider,
    api_key_slot,
    load_config,
    save_config,
)
from backend.llm import generate_playlist_draft, safe_error_message
from backend.youtube import resolve_candidates, search_songs, track_identity_key

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

AI_PROVIDERS = (
    "gemini",
    "openai",
    "anthropic",
    "openrouter_auto",
    "openrouter_free",
    "ollama",
    "custom",
)
OPENROUTER_MODELS = {
    "openrouter_auto": "openrouter/auto",
    "openrouter_free": "openrouter/free",
}

app = FastAPI(
    title="PlaylistMuse",
    description="AI-assisted playlist creation for YouTube Music",
    version="0.6.0",
)
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


class SettingsResponse(BaseModel):
    provider: str
    model: str
    fallback_1: str
    fallback_2: str
    base_url: str
    configured: bool
    api_key_set: bool
    provider_keys_set: dict[str, bool]


class SettingsUpdate(BaseModel):
    provider: Literal[
        "gemini",
        "openai",
        "anthropic",
        "openrouter_auto",
        "openrouter_free",
        "ollama",
        "custom",
    ]
    api_key: str = ""
    model: str = Field(min_length=1, max_length=120)
    fallback_1: str = Field(default="", max_length=120)
    fallback_2: str = Field(default="", max_length=120)
    base_url: str = ""


class PlaylistOptions(BaseModel):
    exclude_live: bool = True
    exclude_covers: bool = True
    exclude_remixes: bool = True


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=1950)
    track_count: int = Field(default=25, ge=5, le=100)
    options: PlaylistOptions = Field(default_factory=PlaylistOptions)

    @field_validator("prompt")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        return " ".join(value.split())


class SeedTrack(BaseModel):
    video_id: str = Field(min_length=3, max_length=32)
    title: str = Field(min_length=1, max_length=300)
    artists: str = Field(min_length=1, max_length=300)
    album: str | None = None
    duration: str | None = None
    thumbnail_url: str | None = None
    url: str | None = None


class SeedGenerateRequest(BaseModel):
    seed: SeedTrack
    track_count: int = Field(default=25, ge=5, le=100)
    options: PlaylistOptions = Field(default_factory=PlaylistOptions)


class PlaylistTrackContext(BaseModel):
    video_id: str | None = Field(default=None, max_length=64)
    title: str = Field(min_length=1, max_length=300)
    artists: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=500)
    reason: str = Field(default="", max_length=600)


class ReplaceTrackRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=1950)
    playlist_name: str = Field(default="", max_length=100)
    playlist_description: str = Field(default="", max_length=500)
    current_track: PlaylistTrackContext
    existing_tracks: list[PlaylistTrackContext] = Field(default_factory=list, max_length=100)
    options: PlaylistOptions = Field(default_factory=PlaylistOptions)

    @field_validator("prompt")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        return " ".join(value.split())


def _settings_response(config: AppConfig) -> SettingsResponse:
    return SettingsResponse(
        provider=config.provider,
        model=config.model,
        fallback_1=config.fallback_1,
        fallback_2=config.fallback_2,
        base_url=config.base_url,
        configured=config.configured,
        api_key_set=api_key_matches_provider(config.provider, config.api_key),
        provider_keys_set={
            provider: config.key_is_saved(provider) for provider in AI_PROVIDERS
        },
    )


def _track_key(title: str, artists: str) -> str:
    return track_identity_key(title, artists)


def _candidate_key(candidate: dict) -> str:
    return track_identity_key(
        str(candidate.get("title", "")),
        str(candidate.get("artist", candidate.get("artists", ""))),
    )


def _replenishment_prompt(
    original_prompt: str,
    playlist_title: str,
    playlist_description: str,
    missing: int,
    pool_size: int,
    tracks: list[dict],
    attempted_candidates: list[dict],
) -> str:
    forbidden_lines: list[str] = []
    for track in tracks:
        forbidden_lines.append(
            f"- {track.get('artists', 'Unknown artist')} — {track.get('title', 'Unknown track')}"
        )
    for candidate in attempted_candidates[-100:]:
        forbidden_lines.append(
            f"- {candidate.get('artist', 'Unknown artist')} — {candidate.get('title', 'Unknown track')}"
        )
    forbidden = "\n".join(dict.fromkeys(forbidden_lines))
    return (
        f"The original playlist request is:\n{original_prompt}\n\n"
        f"Playlist title: {playlist_title}\n"
        f"Playlist description: {playlist_description}\n"
        f"The playlist still needs {missing} resolvable songs. Suggest exactly {pool_size} NEW "
        "replacement candidates that are likely to exist as normal song entries on YouTube Music. "
        "Use canonical released titles and mainstream artist spelling. Do not repeat any forbidden song.\n"
        f"Forbidden or already attempted songs:\n{forbidden or '- None'}"
    )


async def _generate(prompt: str, count: int, options: PlaylistOptions) -> dict:
    config = load_config()
    draft = await generate_playlist_draft(config, prompt, count)
    exclusions = options.model_dump()
    tracks, unresolved = await resolve_candidates(draft["tracks"], exclusions)

    attempted_candidates = list(draft["tracks"])
    attempted_keys = {_candidate_key(candidate) for candidate in attempted_candidates}
    resolved_keys = {
        track_identity_key(track.get("title", ""), track.get("artists", ""))
        for track in tracks
    }
    resolved_ids = {track.get("video_id") for track in tracks if track.get("video_id")}
    stalled_rounds = 0

    for _round in range(1, 7):
        missing = count - len(tracks)
        if missing <= 0:
            break

        pool_size = min(30, max(8, missing * 2))
        refill_prompt = _replenishment_prompt(
            prompt,
            draft["title"],
            draft["description"],
            missing,
            pool_size,
            tracks,
            attempted_candidates,
        )
        refill = await generate_playlist_draft(config, refill_prompt, pool_size)
        fresh_candidates: list[dict] = []
        for candidate in refill["tracks"]:
            key = _candidate_key(candidate)
            if not key or key in attempted_keys:
                continue
            attempted_keys.add(key)
            attempted_candidates.append(candidate)
            fresh_candidates.append(candidate)

        if not fresh_candidates:
            stalled_rounds += 1
            if stalled_rounds >= 2:
                break
            continue

        newly_resolved, newly_unresolved = await resolve_candidates(
            fresh_candidates, exclusions
        )
        unresolved.extend(newly_unresolved)
        added = 0
        for track in newly_resolved:
            track_key = track_identity_key(
                track.get("title", ""), track.get("artists", "")
            )
            video_id = track.get("video_id")
            if track_key in resolved_keys or (video_id and video_id in resolved_ids):
                continue
            resolved_keys.add(track_key)
            if video_id:
                resolved_ids.add(video_id)
            tracks.append(track)
            added += 1
            if len(tracks) >= count:
                break

        stalled_rounds = 0 if added else stalled_rounds + 1
        if stalled_rounds >= 2:
            break

    if len(tracks) < count:
        raise ValueError(
            f"PlaylistMuse found only {len(tracks)} of {count} distinct tracks that could be "
            "verified on YouTube Music. Try a broader prompt or request fewer tracks."
        )

    return {
        "name": draft["title"],
        "description": draft["description"],
        "prompt": prompt,
        "requested_count": count,
        "resolved_count": count,
        "tracks": tracks[:count],
        "unresolved": unresolved,
    }


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "application": "PlaylistMuse"}


@app.get("/api/settings", response_model=SettingsResponse)
async def get_settings() -> SettingsResponse:
    return _settings_response(load_config())


@app.put("/api/settings", response_model=SettingsResponse)
async def update_settings(request: SettingsUpdate) -> SettingsResponse:
    current = load_config()
    provider_api_keys = dict(current.provider_api_keys)
    slot = api_key_slot(request.provider)
    submitted_key = request.api_key.strip()
    if submitted_key and not api_key_matches_provider(request.provider, submitted_key):
        raise HTTPException(
            status_code=400,
            detail="This API key appears to belong to a different AI provider.",
        )
    if submitted_key:
        provider_api_keys[slot] = submitted_key
    active_key = provider_api_keys.get(slot, "")

    model = request.model.strip()
    fallback_1 = request.fallback_1.strip()
    fallback_2 = request.fallback_2.strip()
    base_url = request.base_url.strip()
    if request.provider in OPENROUTER_MODELS:
        model = OPENROUTER_MODELS[request.provider]
        fallback_1 = ""
        fallback_2 = ""
        base_url = ""

    config = AppConfig(
        provider=request.provider,
        api_key=active_key,
        model=model,
        fallback_1=fallback_1,
        fallback_2=fallback_2,
        base_url=base_url,
        provider_api_keys=provider_api_keys,
    )
    save_config(config)
    return _settings_response(config)


@app.get("/api/youtube/status")
async def youtube_status() -> dict:
    return {
        "catalog_available": True,
        "account_connected": False,
        "message": "Public YouTube Music catalogue available",
    }


@app.get("/api/seeds/search")
async def seed_search(
    q: str = Query(..., min_length=2, max_length=300),
    limit: int = Query(default=8, ge=1, le=20),
) -> dict:
    try:
        songs = await search_songs(q.strip(), limit)
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail="YouTube Music search is temporarily unavailable.",
        ) from error
    return {"query": q, "results": songs}


@app.post("/api/playlists/generate")
async def generate_playlist(request: GenerateRequest) -> dict:
    try:
        return await _generate(request.prompt, request.track_count, request.options)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=safe_error_message(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail="Playlist generation failed. Please try again.",
        ) from error


@app.post("/api/playlists/generate-from-seed")
async def generate_from_seed(request: SeedGenerateRequest) -> dict:
    seed = request.seed
    prompt = (
        f"Create a cohesive playlist inspired by the song '{seed.title}' by {seed.artists}. "
        "Match its style, mood, energy and musical character while including varied compatible artists."
    )
    try:
        result = await _generate(prompt, request.track_count, request.options)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=safe_error_message(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail="Playlist generation failed. Please try again.",
        ) from error

    seed_payload = seed.model_dump()
    seed_key = track_identity_key(seed.title, seed.artists)
    matching_track = next(
        (
            track
            for track in result["tracks"]
            if track_identity_key(
                track.get("title", ""), track.get("artists", "")
            )
            == seed_key
        ),
        None,
    )
    seed_payload["description"] = (
        (matching_track or {}).get("description")
        or "The reference song that establishes the playlist's core sound, mood and energy."
    )
    seed_payload["reason"] = (
        (matching_track or {}).get("reason")
        or "It anchors the sequence because every other selection was chosen in response to its musical character."
    )

    remaining_tracks = [
        track
        for track in result["tracks"]
        if track.get("video_id") != seed.video_id
        and track_identity_key(track.get("title", ""), track.get("artists", ""))
        != seed_key
    ]
    result["tracks"] = [seed_payload, *remaining_tracks][: request.track_count]
    result["resolved_count"] = len(result["tracks"])
    result["seed"] = seed_payload
    return result


@app.post("/api/playlists/replace-track")
async def replace_track(request: ReplaceTrackRequest) -> dict:
    current = request.current_track
    avoided = "\n".join(
        f"- {track.artists} — {track.title}" for track in request.existing_tracks
    )
    replacement_prompt = (
        "Suggest exactly 6 strong replacement candidates for one song in an existing playlist.\n"
        f"Original playlist request: {request.prompt}\n"
        f"Playlist title: {request.playlist_name or 'Untitled playlist'}\n"
        f"Playlist description: {request.playlist_description or 'Not provided'}\n"
        f"Song being replaced: {current.artists} — {current.title}\n"
        f"Its role in the playlist: {current.reason or 'Maintain the same mood, energy and sequencing role.'}\n"
        "Choose alternatives that preserve or improve that role while adding variety. "
        "Do not return the current song or any song already in the playlist.\n"
        f"Songs to avoid:\n{avoided or '- None'}"
    )

    try:
        config = load_config()
        draft = await generate_playlist_draft(config, replacement_prompt, 6)
        candidates, _ = await resolve_candidates(
            draft["tracks"], request.options.model_dump()
        )
        existing_ids = {
            track.video_id for track in request.existing_tracks if track.video_id
        }
        existing_keys = {
            _track_key(track.title, track.artists) for track in request.existing_tracks
        }
        existing_keys.add(_track_key(current.title, current.artists))
        for candidate in candidates:
            if candidate.get("video_id") in existing_ids:
                continue
            if _track_key(
                candidate.get("title", ""), candidate.get("artists", "")
            ) in existing_keys:
                continue
            return {"track": candidate}
        raise ValueError("No suitable non-duplicate replacement could be resolved.")
    except ValueError as error:
        raise HTTPException(status_code=400, detail=safe_error_message(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail="Track replacement failed. Please try again.",
        ) from error


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html", headers={"Cache-Control": "no-cache"})
