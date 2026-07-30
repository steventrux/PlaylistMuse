"""FastAPI routes for optional album artwork enrichment."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from backend.artwork import artwork_image_path, resolve_track_artwork

router = APIRouter(prefix="/artwork", tags=["artwork"])


class TrackArtworkRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    artists: str = Field(min_length=1, max_length=300)
    album: str | None = Field(default=None, max_length=300)
    thumbnail_url: str | None = Field(default=None, max_length=2000)

    @field_validator("title", "artists")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("album", "thumbnail_url")
    @classmethod
    def trim_optional_text(cls, value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None


@router.post("/track")
async def track_artwork(request: TrackArtworkRequest) -> dict:
    return await resolve_track_artwork(**request.model_dump())


@router.get("/images/{filename}")
async def artwork_image(filename: str) -> FileResponse:
    path = artwork_image_path(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="Artwork not found.")
    return FileResponse(
        path,
        headers={"Cache-Control": "public, max-age=2592000, immutable"},
    )
