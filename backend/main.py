"""PlaylistMuse FastAPI application."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config import (
    AppConfig,
    api_key_matches_provider,
    api_key_slot,
    load_config,
    save_config,
)
from backend.llm import generate_playlist_draft, safe_error_message
from backend.schemas import (
    GenerateRequest,
    PlaylistOptions,
    ReplaceTrackRequest,
    SeedGenerateRequest,
    SettingsResponse,
    SettingsUpdate,
)
from backend.services.playlist_generation import generate_playlist as generate_playlist_service
from backend.youtube import resolve_candidates, search_songs, track_identity_key
from backend.youtube_routes import router as youtube_router

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
    version="0.7.0",
)
app.include_router(youtube_router)
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


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


async def _generate(prompt: str, count: int, options: PlaylistOptions) -> dict:
    """Compatibility wrapper preserving the existing route integration point."""
    return await generate_playlist_service(prompt, count, options)


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
        f"Create a cohesive playlist inspired by the song '{seed.title}' by "
        f"{seed.artists}. Match its style, mood, energy and musical character while "
        "including varied compatible artists."
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
                track.get("title", ""),
                track.get("artists", ""),
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
        f"Its role in the playlist: "
        f"{current.reason or 'Maintain the same mood, energy and sequencing role.'}\n"
        "Choose alternatives that preserve or improve that role while adding variety. "
        "Do not return the current song or any song already in the playlist.\n"
        f"Songs to avoid:\n{avoided or '- None'}"
    )

    try:
        config = load_config()
        draft = await generate_playlist_draft(config, replacement_prompt, 6)
        candidates, _ = await resolve_candidates(
            draft["tracks"],
            request.options.model_dump(),
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
                candidate.get("title", ""),
                candidate.get("artists", ""),
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
