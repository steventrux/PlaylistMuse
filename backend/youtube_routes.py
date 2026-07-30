"""FastAPI routes for YouTube Music account connection and publishing."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from backend.artwork_routes import router as artwork_router
from backend.youtube_account import (
    YouTubeAccountError,
    disconnect_youtube,
    poll_authorization,
    save_youtube_settings,
    start_authorization,
    youtube_settings_response,
    youtube_status,
)
from backend.youtube_publish import create_youtube_playlist

router = APIRouter(prefix="/api")
router.include_router(artwork_router)


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
        )
    except YouTubeAccountError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail="YouTube Music could not create the playlist. Please try again.",
        ) from error
