"""PlaylistMuse FastAPI application."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from backend.config import AppConfig, load_config, save_config
from backend.llm import generate_candidates
from backend.youtube import resolve_candidates

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"

app = FastAPI(
    title="PlaylistMuse",
    description="AI-assisted playlist creation for YouTube Music",
    version="0.1.0",
)
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


class SettingsResponse(BaseModel):
    provider: str
    model: str
    base_url: str
    configured: bool
    api_key_set: bool


class SettingsUpdate(BaseModel):
    provider: Literal["gemini", "openai", "anthropic", "ollama", "custom"]
    api_key: str = ""
    model: str = Field(min_length=1, max_length=120)
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


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "application": "PlaylistMuse"}


@app.get("/api/settings", response_model=SettingsResponse)
async def get_settings() -> SettingsResponse:
    config = load_config()
    return SettingsResponse(
        provider=config.provider,
        model=config.model,
        base_url=config.base_url,
        configured=config.configured,
        api_key_set=bool(config.api_key),
    )


@app.put("/api/settings", response_model=SettingsResponse)
async def update_settings(request: SettingsUpdate) -> SettingsResponse:
    current = load_config()
    api_key = request.api_key.strip() or current.api_key
    config = AppConfig(
        provider=request.provider,
        api_key=api_key,
        model=request.model.strip(),
        base_url=request.base_url.strip(),
    )
    save_config(config)
    return SettingsResponse(
        provider=config.provider,
        model=config.model,
        base_url=config.base_url,
        configured=config.configured,
        api_key_set=bool(config.api_key),
    )


@app.post("/api/playlists/generate")
async def generate_playlist(request: GenerateRequest) -> dict:
    config = load_config()
    try:
        candidates = await generate_candidates(config, request.prompt, request.track_count)
        tracks, unresolved = await resolve_candidates(candidates, request.options.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Playlist generation failed: {exc}") from exc

    return {
        "name": request.prompt[:80],
        "prompt": request.prompt,
        "requested_count": request.track_count,
        "resolved_count": len(tracks),
        "tracks": tracks,
        "unresolved": unresolved,
    }


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html", headers={"Cache-Control": "no-cache"})
