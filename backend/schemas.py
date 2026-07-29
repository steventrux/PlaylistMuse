"""Pydantic request and response models for the PlaylistMuse API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


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
    existing_tracks: list[PlaylistTrackContext] = Field(default_factory=list, max_length=300)
    options: PlaylistOptions = Field(default_factory=PlaylistOptions)

    @field_validator("prompt")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        return " ".join(value.split())
