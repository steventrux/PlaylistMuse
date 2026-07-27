"""PlaylistMuse FastAPI application."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from backend.config import AppConfig, load_config, save_config
from backend.llm import generate_candidates
from backend.youtube import resolve_candidates, search_songs

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

app = FastAPI(
    title="PlaylistMuse",
    description="AI-assisted playlist creation for YouTube Music",
    version="0.2.0",
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


class SettingsUpdate(BaseModel):
    provider: Literal["gemini", "openai", "anthropic", "ollama", "custom"]
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


def _settings_response(config: AppConfig) -> SettingsResponse:
    return SettingsResponse(
        provider=config.provider,
        model=config.model,
        fallback_1=config.fallback_1,
        fallback_2=config.fallback_2,
        base_url=config.base_url,
        configured=config.configured,
        api_key_set=bool(config.api_key),
    )


async def _generate(prompt: str, count: int, options: PlaylistOptions) -> dict:
    config = load_config()
    candidates = await generate_candidates(config, prompt, count)
    tracks, unresolved = await resolve_candidates(candidates, options.model_dump())
    return {
        "name": prompt[:80],
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
    config = AppConfig(
        provider=request.provider,
        api_key=request.api_key.strip() or current.api_key,
        model=request.model.strip(),
        fallback_1=request.fallback_1.strip(),
        fallback_2=request.fallback_2.strip(),
        base_url=request.base_url.strip(),
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
    existing_ids = {track.get("video_id") for track in result["tracks"]}
    if seed.video_id not in existing_ids:
        result["tracks"].insert(0, seed_payload)
        result["tracks"] = result["tracks"][: request.track_count]
        result["resolved_count"] = len(result["tracks"])
    result["name"] = f"Inspired by {seed.title}"
    result["seed"] = seed_payload
    return result


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html", headers={"Cache-Control": "no-cache"})
