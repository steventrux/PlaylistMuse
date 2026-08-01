"""FastAPI routes for service setup and YouTube Music publishing."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from backend.config import (
    AppConfig,
    activate_provider,
    disconnect_provider,
    load_config,
    save_config,
)
from backend.onboarding import acknowledge_onboarding, onboarding_status
from backend.playlist_cover import normalize_thumbnail_urls
from backend.youtube_account import (
    YouTubeAccountError,
    disconnect_youtube,
    poll_authorization,
    save_youtube_settings,
    start_authorization,
    youtube_settings_response,
    youtube_status,
)
from backend.youtube_playlist_service import create_youtube_playlist

router = APIRouter(prefix="/api")

AIProviderName = Literal[
    "gemini",
    "openai",
    "anthropic",
    "openrouter_auto",
    "openrouter_free",
    "ollama",
    "custom",
]
AI_PROVIDERS: tuple[str, ...] = (
    "gemini",
    "openai",
    "anthropic",
    "openrouter_auto",
    "openrouter_free",
    "ollama",
    "custom",
)


class AIProviderActivation(BaseModel):
    provider: AIProviderName


class YouTubeSettingsUpdate(BaseModel):
    client_id: str = Field(min_length=1, max_length=300)
    client_secret: str = Field(default="", max_length=300)

    @field_validator("client_id", "client_secret")
    @classmethod
    def trim_value(cls, value: str) -> str:
        return value.strip()


class YouTubePlaylistCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    privacy_status: Literal["PRIVATE", "UNLISTED", "PUBLIC"] = "PRIVATE"
    video_ids: list[str] = Field(min_length=1, max_length=100)
    thumbnail_urls: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("title", "description")
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("video_ids")
    @classmethod
    def normalize_video_ids(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if not normalized:
            raise ValueError("At least one valid YouTube Music track is required.")
        return normalized

    @field_validator("thumbnail_urls")
    @classmethod
    def validate_thumbnail_urls(cls, values: list[str]) -> list[str]:
        return normalize_thumbnail_urls(values)


def _ensure_active_ai_config(config: AppConfig) -> AppConfig:
    if config.configured:
        return config
    for provider in AI_PROVIDERS:
        candidate = config.configuration_for(provider)
        if candidate.configured:
            save_config(candidate)
            return load_config()
    return config


def _ai_profiles_response(config: AppConfig) -> dict:
    profiles: dict[str, dict] = {}
    for provider in AI_PROVIDERS:
        profile = config.profile_for(provider)
        profiles[provider] = {
            **profile,
            "configured": config.is_provider_configured(provider),
            "api_key_set": config.key_is_saved(provider),
            "active": provider == config.provider and config.configured,
        }
    return {
        "active_provider": config.provider if config.configured else "",
        "configured": config.configured,
        "profiles": profiles,
    }


@router.get("/onboarding", tags=["onboarding"])
async def get_onboarding_status() -> dict[str, bool]:
    return onboarding_status()


@router.post("/onboarding/acknowledge", tags=["onboarding"])
async def acknowledge_initial_setup() -> dict[str, bool]:
    return acknowledge_onboarding()


@router.get("/ai/profiles", tags=["ai-settings"])
async def get_ai_profiles() -> dict:
    return _ai_profiles_response(_ensure_active_ai_config(load_config()))


@router.post("/ai/activate", tags=["ai-settings"])
async def activate_ai_provider(request: AIProviderActivation) -> dict:
    try:
        updated = activate_provider(request.provider)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if updated.provider != request.provider or not updated.configured:
        raise HTTPException(
            status_code=500,
            detail="The selected AI provider could not be activated.",
        )
    return _ai_profiles_response(updated)


@router.delete("/ai/providers/{provider}", tags=["ai-settings"])
async def delete_ai_provider(provider: str) -> dict:
    if provider not in AI_PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown AI provider.")
    updated = disconnect_provider(provider)
    return _ai_profiles_response(_ensure_active_ai_config(updated))


@router.get("/youtube/settings", tags=["youtube-music"])
async def get_youtube_settings() -> dict:
    return youtube_settings_response()


@router.put("/youtube/settings", tags=["youtube-music"])
async def update_youtube_settings(request: YouTubeSettingsUpdate) -> dict:
    try:
        return save_youtube_settings(request.client_id, request.client_secret)
    except YouTubeAccountError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail="Google OAuth settings could not be saved.",
        ) from error


@router.get("/youtube/status", tags=["youtube-music"])
async def get_youtube_status() -> dict:
    return await youtube_status()


@router.post("/youtube/connect/start", tags=["youtube-music"])
async def begin_youtube_connection() -> dict:
    try:
        return await start_authorization()
    except YouTubeAccountError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=(
                "Google could not start the authorization flow. Check the OAuth client "
                "and ensure the YouTube Data API is enabled."
            ),
        ) from error


@router.post("/youtube/connect/poll", tags=["youtube-music"])
async def poll_youtube_connection() -> dict:
    try:
        return await poll_authorization()
    except YouTubeAccountError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail="Google authorization could not be completed.",
        ) from error


@router.delete("/youtube/connection", tags=["youtube-music"])
async def delete_youtube_connection() -> dict:
    return await disconnect_youtube()


@router.post("/youtube/playlists", tags=["youtube-music"])
async def publish_youtube_playlist(request: YouTubePlaylistCreateRequest) -> dict:
    try:
        return await create_youtube_playlist(
            request.title,
            request.description,
            request.privacy_status,
            request.video_ids,
            request.thumbnail_urls,
        )
    except YouTubeAccountError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail="YouTube Music could not create the playlist. Please try again.",
        ) from error
