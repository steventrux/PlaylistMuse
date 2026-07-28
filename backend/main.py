"""PlaylistMuse FastAPI application."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from backend.config import AppConfig, api_key_slot, load_config, save_config
from backend.llm import generate_playlist_draft
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
    version="0.5.0",
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
        api_key_set=bool(config.api_key),
        provider_keys_set={
            provider: config.key_is_saved(provider) for provider in AI_PROVIDERS
        },
    )


def _track_key(title: str, artists: str) -> str:
    return track_identity_key(title, artists)


async def _generate(prompt: str, count: int, options: PlaylistOptions) -> dict:
    config = load_config()
    draft = await generate_playlist_draft(config, prompt, count)
    tracks, unresolved = await resolve_candidates(draft["tracks"], options.model_dump())
    return {
        "name": draft["title"],
        "description": draft["description"],
        "prompt": prompt,
        "requested_count": count,
        "resolved_count": len(tracks),
        "tracks": tracks,
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
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"YouTube Music search failed: {exc}") from exc
    return {"query": q, "results": songs}


@app.post("/api/playlists/generate")
async def generate_playlist(request: GenerateRequest) -> dict:
    try:
        return await _generate(request.prompt, request.track_count, request.options)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Playlist generation failed: {exc}") from exc


@app.post("/api/playlists/generate-from-seed")
async def generate_from_seed(request: SeedGenerateRequest) -> dict:
    seed = request.seed
    prompt = (
        f"Create a cohesive playlist inspired by the song '{seed.title}' by {seed.artists}. "
        "Match its style, mood, energy and musical character while including varied compatible artists."
    )
    try:
        result = await _generate(prompt, request.track_count, request.options)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Playlist generation failed: {exc}") from exc

    seed_payload = seed.model_dump()
    seed_key = track_identity_key(seed.title, seed.artists)

    matching_track = next(
        (
            track
            for track in result["tracks"]
            if track_identity_key(track.get("title", ""), track.get("artists", "")) == seed_key
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
        and track_identity_key(track.get("title", ""), track.get("artists", "")) != seed_key
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
        candidates, _ = await resolve_candidates(draft["tracks"], request.options.model_dump())

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
            if _track_key(candidate.get("title", ""), candidate.get("artists", "")) in existing_keys:
                continue
            return {"track": candidate}

        raise ValueError("No suitable non-duplicate replacement could be resolved.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Track replacement failed: {exc}") from exc


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html", headers={"Cache-Control": "no-cache"})
