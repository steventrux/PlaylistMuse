"""FastAPI routes for optional playlist artwork enrichment."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from backend.artwork import resolve_playlist_artwork

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


class PlaylistArtworkRequest(BaseModel):
    tracks: list[TrackArtworkRequest] = Field(min_length=1, max_length=4)


@router.post("/playlist")
async def playlist_artwork(request: PlaylistArtworkRequest) -> dict:
    return {
        "tracks": await resolve_playlist_artwork(
            [track.model_dump() for track in request.tracks]
        )
    }
