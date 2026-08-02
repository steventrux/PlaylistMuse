"""PlaylistMuse FastAPI application."""

from __future__ import annotations

import re
from contextvars import ContextVar
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
from backend.lastfm_discovery import (
    discover_for_seed as similar_track_candidates,
    discover_from_anchors,
    select_prompt_anchors,
)
from backend.llm import generate_playlist_draft, safe_error_message
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
MAX_REPLENISHMENT_ROUNDS = 6
MAX_STALLED_ROUNDS = 2
MAX_LASTFM_CONTEXT_TRACKS = 60
SeedMode = Literal["strict", "balanced", "exploratory"]
_ARTIST_SEPARATOR_RE = re.compile(
    r"\s*(?:,|&|\bfeat\.?\b|\bfeaturing\b|\bwith\b)\s*",
    re.IGNORECASE,
)

_SEED_RECOMMENDATIONS: ContextVar[tuple[dict[str, str], ...]] = ContextVar(
    "playlistmuse_seed_recommendations",
    default=(),
)
_SEED_ANCHORS: ContextVar[tuple[dict[str, str], ...]] = ContextVar(
    "playlistmuse_seed_anchors",
    default=(),
)
_SEED_MODE: ContextVar[str] = ContextVar(
    "playlistmuse_seed_mode",
    default="",
)

app = FastAPI(
    title="PlaylistMuse",
    description="AI-assisted playlist creation for YouTube Music",
    version="0.7.0",
)
app.include_router(youtube_router)
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


def _normalize_prompt_text(value: str) -> str:
    return " ".join(value.split())


def _constraint_priority_prompt(prompt: str) -> str:
    """Make literal user constraints outrank editorial flow and creative interpretation."""
    return (
        "Follow the user's request literally. First identify every explicit constraint, "
        "including dates, years, eras, languages, countries, markets, genres, exclusions, "
        "artist limits, quantities and words such as only, exclusively, exactly, before "
        "or after. Treat those constraints as mandatory and never relax, reinterpret or "
        "silently broaden them to improve flow, variety, familiarity or storytelling. "
        "Use musical progression only to order tracks that already satisfy all mandatory "
        "constraints. If uncertain whether a song complies, do not include it. Do not "
        "substitute a famous or stylistically suitable song from another year, language, "
        "country or category.\n\n"
        f"User request:\n{prompt}"
    )


def _seed_mode_instruction(mode: str) -> str:
    if mode == "strict":
        return (
            "STRICT seed mode: musical similarity to the seed is the primary mandatory "
            "criterion. Prefer exact Last.fm similar-track evidence. Keep style, timbre, "
            "energy, mood and era close to the seed. Do not add contrast tracks, broad "
            "genre neighbours or famous songs merely to create a journey. Variety and "
            "flow must never weaken similarity."
        )
    if mode == "exploratory":
        return (
            "EXPLORATORY seed mode: begin close to the seed, then allow a wider sequence "
            "through defensible musical links. Every track must still connect through at "
            "least one concrete characteristic such as sound, rhythm, mood, instrumentation, "
            "scene or artist affinity. Avoid arbitrary contrast or unrelated hits."
        )
    return (
        "BALANCED seed mode: keep the seed clearly central. Most tracks should be close "
        "matches supported by Last.fm or strong musical affinity, with a limited number "
        "of compatible variations. Flow may organise the result but may not override "
        "similarity to the seed."
    )


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
        return _normalize_prompt_text(value)


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
    seed_mode: SeedMode = "balanced"
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
        return _normalize_prompt_text(value)


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


def _candidate_key(candidate: dict) -> str:
    return track_identity_key(
        str(candidate.get("title", "")),
        str(candidate.get("artist", candidate.get("artists", ""))),
    )


def _artist_key(candidate: dict) -> str:
    return track_identity_key(
        "",
        str(candidate.get("artist", candidate.get("artists", ""))),
    )


def _artist_identity_keys(value: str) -> set[str]:
    """Return both the complete credit and its common collaborator components."""
    normalized = " ".join(str(value).split())
    if not normalized:
        return set()
    keys = {track_identity_key("", normalized)}
    for part in _ARTIST_SEPARATOR_RE.split(normalized):
        part = part.strip()
        if part:
            keys.add(track_identity_key("", part))
    return keys


def _blend_candidates(
    primary: list[dict[str, str]],
    supplemental: list[dict[str, str]],
    count: int,
) -> list[dict[str, str]]:
    """Legacy bounded blending helper retained for compatibility with older tests."""
    combined_primary = list(primary)
    seen = {_candidate_key(candidate) for candidate in combined_primary}
    seen.discard("")
    quota = min(len(supplemental), max(1, min(12, count // 5)))
    extras: list[dict[str, str]] = []
    for candidate in supplemental:
        key = _candidate_key(candidate)
        if not key or key in seen:
            continue
        seen.add(key)
        extras.append(candidate)
        if len(extras) >= quota:
            break

    if not extras:
        return combined_primary
    if not combined_primary:
        return extras

    blended = list(combined_primary)
    spacing = max(1, len(combined_primary) // (len(extras) + 1))
    offset = spacing
    for candidate in extras:
        blended.insert(min(offset, len(blended)), candidate)
        offset += spacing + 1
    return blended


def _discovery_prompt(
    original_prompt: str,
    first_draft: dict,
    candidates: list[dict[str, str]],
    count: int,
    *,
    seed_mode: str = "",
) -> str:
    first_pass = "\n".join(
        f"- {track.get('artist', 'Unknown artist')} — "
        f"{track.get('title', 'Unknown track')}"
        for track in first_draft.get("tracks", [])[:count]
    )
    evidence = "\n".join(
        f"- {candidate.get('artist', 'Unknown artist')} — "
        f"{candidate.get('title', 'Unknown track')} "
        f"[{candidate.get('lastfm_strategy', 'lastfm')}]"
        for candidate in candidates[:MAX_LASTFM_CONTEXT_TRACKS]
    )
    seed_instruction = f"\n{_seed_mode_instruction(seed_mode)}\n" if seed_mode else ""
    return (
        f"Create the final playlist for this request:\n{original_prompt}\n\n"
        "MANDATORY PRIORITY: preserve every explicit constraint in the original request. "
        "Dates, years, eras, languages, countries, markets, exclusions and words such as "
        "only or exactly are hard filters. A candidate that violates one must be rejected, "
        "even if it improves coherence, discovery, variety or flow. Never silently broaden "
        "the request. Musical flow may only order already compliant tracks."
        f"{seed_instruction}\n"
        "You have two complementary inputs:\n"
        "1. Your own first-pass musical ideas.\n"
        "2. Last.fm collaborative-listening evidence derived from the seed or from "
        "representative tracks in the first pass.\n\n"
        f"First-pass ideas:\n{first_pass or '- None'}\n\n"
        f"Last.fm evidence:\n{evidence or '- None'}\n\n"
        f"Return a final playlist of up to {count} tracks. Use Last.fm evidence only when "
        "it satisfies the original request and the selected seed mode. You may select "
        "tracks not listed above only when they satisfy every mandatory constraint and "
        "have a clear musical justification. Do not add contrast tracks merely to create "
        "a narrative arc. For every selected song, write a natural song description and "
        "a playlist-specific reason. Use canonical artist and released track names."
    )


def _annotate_lastfm_sources(
    tracks: list[dict[str, str]],
    candidates: list[dict[str, str]],
) -> list[dict[str, str]]:
    evidence_by_key = {
        _candidate_key(candidate): candidate
        for candidate in candidates
        if _candidate_key(candidate)
    }
    annotated: list[dict[str, str]] = []
    for track in tracks:
        copy = dict(track)
        evidence = evidence_by_key.get(_candidate_key(copy))
        if evidence and evidence.get("lastfm_strategy") == "similar_track":
            copy["source"] = "lastfm"
            copy["lastfm_strategy"] = "similar_track"
        annotated.append(copy)
    return annotated


def _anchor_metadata(anchors: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "artist": str(anchor.get("artist", "")).strip(),
            "title": str(anchor.get("title", "")).strip(),
            "kind": str(anchor.get("kind", "ai_draft")).strip() or "ai_draft",
        }
        for anchor in anchors
        if str(anchor.get("artist", "")).strip()
        and str(anchor.get("title", "")).strip()
    ]


def _selection_sets(
    selected_tracks: list[dict],
) -> tuple[set[str], set[str]]:
    track_keys = {
        track_identity_key(track.get("title", ""), track.get("artists", ""))
        for track in selected_tracks
    }
    artist_keys: set[str] = set()
    for track in selected_tracks:
        artist_keys.update(_artist_identity_keys(str(track.get("artists", ""))))
    return track_keys, artist_keys


def _signal_metadata(
    candidates: list[dict[str, str]],
    selected_tracks: list[dict],
) -> list[dict[str, object]]:
    selected_track_keys, selected_artist_keys = _selection_sets(selected_tracks)
    signals: list[dict[str, object]] = []
    for candidate in candidates:
        strategy = str(candidate.get("lastfm_strategy", "")).strip()
        is_track_signal = strategy == "similar_track"
        signal: dict[str, object] = {
            "artist": str(candidate.get("artist", "")).strip(),
            "title": str(candidate.get("title", "")).strip() if is_track_signal else None,
            "strategy": strategy or "lastfm",
            "match": str(candidate.get("lastfm_match", "")).strip() or None,
            "selected": is_track_signal
            and _candidate_key(candidate) in selected_track_keys,
            "artist_represented": _artist_key(candidate) in selected_artist_keys,
        }
        anchor_artist = str(candidate.get("anchor_artist", "")).strip()
        anchor_title = str(candidate.get("anchor_title", "")).strip()
        if anchor_artist and anchor_title:
            signal["anchor"] = {
                "artist": anchor_artist,
                "title": anchor_title,
            }
        signals.append(signal)
    return signals


def _represented_counts(signals: list[dict[str, object]]) -> tuple[int, int]:
    represented_signals = sum(
        1 for signal in signals if bool(signal.get("artist_represented"))
    )
    represented_artist_keys = {
        track_identity_key("", str(signal.get("artist", "")))
        for signal in signals
        if bool(signal.get("artist_represented"))
        and str(signal.get("artist", "")).strip()
    }
    return represented_signals, len(represented_artist_keys)


def _lastfm_summary(
    anchors: list[dict[str, str]],
    candidates: list[dict[str, str]],
    selected_tracks: list[dict],
    *,
    guidance_applied: bool,
) -> dict[str, object]:
    signals = _signal_metadata(candidates, selected_tracks)
    strategies = sorted(
        {
            str(candidate.get("lastfm_strategy", "")).strip()
            for candidate in candidates
            if str(candidate.get("lastfm_strategy", "")).strip()
        }
    )
    selected = sum(1 for signal in signals if bool(signal["selected"]))
    represented_signals, represented_artists = _represented_counts(signals)
    return {
        "available": bool(candidates),
        "guidance_applied": guidance_applied,
        "suggestions": len(candidates),
        "selected": selected,
        "represented_signals": represented_signals,
        "represented_artists": represented_artists,
        "strategies": strategies,
        "anchors": _anchor_metadata(anchors),
        "signals": signals,
    }


def _refresh_lastfm_selection(summary: dict, selected_tracks: list[dict]) -> None:
    signals = summary.get("signals")
    if not isinstance(signals, list):
        return
    selected_track_keys, selected_artist_keys = _selection_sets(selected_tracks)
    selected = 0
    typed_signals: list[dict[str, object]] = []
    for signal in signals:
        if not isinstance(signal, dict):
            continue
        artist = str(signal.get("artist", "")).strip()
        title = str(signal.get("title") or "").strip()
        strategy = str(signal.get("strategy", "")).strip()
        signal["selected"] = (
            strategy == "similar_track"
            and track_identity_key(title, artist) in selected_track_keys
        )
        signal["artist_represented"] = (
            track_identity_key("", artist) in selected_artist_keys
        )
        selected += int(bool(signal["selected"]))
        typed_signals.append(signal)
    represented_signals, represented_artists = _represented_counts(typed_signals)
    summary["selected"] = selected
    summary["represented_signals"] = represented_signals
    summary["represented_artists"] = represented_artists


def _replenishment_prompt(
    original_prompt: str,
    playlist_title: str,
    playlist_description: str,
    missing: int,
    pool_size: int,
    tracks: list[dict],
    attempted_candidates: list[dict],
    lastfm_candidates: list[dict[str, str]] | None = None,
    *,
    seed_mode: str = "",
) -> str:
    forbidden_lines: list[str] = []
    for track in tracks:
        forbidden_lines.append(
            f"- {track.get('artists', 'Unknown artist')} — "
            f"{track.get('title', 'Unknown track')}"
        )
    for candidate in attempted_candidates[-100:]:
        forbidden_lines.append(
            f"- {candidate.get('artist', 'Unknown artist')} — "
            f"{candidate.get('title', 'Unknown track')}"
        )
    forbidden = "\n".join(dict.fromkeys(forbidden_lines))
    evidence = "\n".join(
        f"- {candidate.get('artist', 'Unknown artist')} — "
        f"{candidate.get('title', 'Unknown track')}"
        for candidate in (lastfm_candidates or [])[:30]
    )
    discovery_note = (
        "\nLast.fm collaborative evidence remains available. Use it only when it "
        "satisfies all original constraints:\n"
        f"{evidence}\n"
        if evidence
        else ""
    )
    seed_instruction = f"\n{_seed_mode_instruction(seed_mode)}\n" if seed_mode else ""
    return (
        f"The original playlist request is:\n{original_prompt}\n\n"
        "Every explicit condition in that request remains mandatory during replenishment. "
        "Do not broaden dates, years, language, country, market, genre, exclusions or any "
        "other stated limit merely to fill the requested count. If a candidate is uncertain "
        "or non-compliant, do not propose it."
        f"{seed_instruction}\n"
        f"Playlist title: {playlist_title}\n"
        f"Playlist description: {playlist_description}\n"
        f"The playlist still needs {missing} resolvable songs. Suggest exactly "
        f"{pool_size} NEW replacement candidates that are likely to exist as normal "
        "song entries on YouTube Music and that satisfy every original constraint. "
        "Use canonical released titles and mainstream artist spelling. Do not repeat "
        "any forbidden song."
        f"{discovery_note}\n"
        f"Forbidden or already attempted songs:\n{forbidden or '- None'}"
    )


async def _generate(prompt: str, count: int, options: PlaylistOptions) -> dict:
    config = load_config()
    seed_mode = _SEED_MODE.get()
    first_draft = await generate_playlist_draft(
        config,
        _constraint_priority_prompt(prompt),
        count,
    )

    lastfm_anchors = list(_SEED_ANCHORS.get())
    lastfm_candidates = list(_SEED_RECOMMENDATIONS.get())
    if not lastfm_candidates:
        prompt_anchors = select_prompt_anchors(first_draft.get("tracks", []))
        lastfm_anchors.extend(
            {
                "artist": anchor["artist"],
                "title": anchor["title"],
                "kind": "ai_draft",
            }
            for anchor in prompt_anchors
        )
        lastfm_candidates = await discover_from_anchors(
            prompt_anchors,
            limit=min(MAX_LASTFM_CONTEXT_TRACKS, max(20, count * 2)),
        )

    draft = first_draft
    guidance_applied = False
    if lastfm_candidates:
        guided_prompt = _discovery_prompt(
            prompt,
            first_draft,
            lastfm_candidates,
            count,
            seed_mode=seed_mode,
        )
        try:
            draft = await generate_playlist_draft(config, guided_prompt, count)
            guidance_applied = True
        except Exception:
            draft = first_draft

    draft_tracks = _annotate_lastfm_sources(
        list(draft.get("tracks", [])),
        lastfm_candidates,
    )
    exclusions = options.model_dump()
    tracks, unresolved = await resolve_candidates(draft_tracks, exclusions)

    attempted_candidates = list(draft_tracks)
    attempted_keys = {_candidate_key(candidate) for candidate in attempted_candidates}
    resolved_keys = {
        track_identity_key(track.get("title", ""), track.get("artists", ""))
        for track in tracks
    }
    resolved_ids = {track.get("video_id") for track in tracks if track.get("video_id")}

    stalled_rounds = 0
    for _ in range(MAX_REPLENISHMENT_ROUNDS):
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
            lastfm_candidates,
            seed_mode=seed_mode,
        )
        refill = await generate_playlist_draft(config, refill_prompt, pool_size)
        refill_tracks = _annotate_lastfm_sources(
            list(refill.get("tracks", [])),
            lastfm_candidates,
        )
        fresh_candidates: list[dict] = []
        for candidate in refill_tracks:
            key = _candidate_key(candidate)
            if not key or key in attempted_keys:
                continue
            attempted_keys.add(key)
            attempted_candidates.append(candidate)
            fresh_candidates.append(candidate)

        if not fresh_candidates:
            stalled_rounds += 1
            if stalled_rounds >= MAX_STALLED_ROUNDS:
                break
            continue

        newly_resolved, newly_unresolved = await resolve_candidates(
            fresh_candidates,
            exclusions,
        )
        unresolved.extend(newly_unresolved)
        added = 0
        for track in newly_resolved:
            track_key = track_identity_key(
                track.get("title", ""),
                track.get("artists", ""),
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
        if stalled_rounds >= MAX_STALLED_ROUNDS:
            break

    if len(tracks) < count:
        raise ValueError(
            f"PlaylistMuse found only {len(tracks)} of {count} distinct tracks that "
            "could be verified on YouTube Music without deliberately relaxing the "
            "request. Try a broader prompt or request fewer tracks."
        )

    final_tracks = tracks[:count]
    return {
        "name": draft["title"],
        "description": draft["description"],
        "prompt": prompt,
        "requested_count": count,
        "resolved_count": count,
        "tracks": final_tracks,
        "unresolved": unresolved,
        "lastfm": _lastfm_summary(
            lastfm_anchors,
            lastfm_candidates,
            final_tracks,
            guidance_applied=guidance_applied,
        ),
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
        f"Create a playlist from the seed song '{seed.title}' by {seed.artists}. "
        f"{_seed_mode_instruction(request.seed_mode)} The seed must remain the primary "
        "reference for every selection. Do not let editorial sequencing or a narrative "
        "journey override the selected similarity mode."
    )
    lastfm_candidates = await similar_track_candidates(
        seed.artists,
        seed.title,
        limit=min(MAX_LASTFM_CONTEXT_TRACKS, max(20, request.track_count * 2)),
    )
    seed_anchor = {
        "artist": seed.artists,
        "title": seed.title,
        "kind": "seed",
    }
    recommendation_token = _SEED_RECOMMENDATIONS.set(tuple(lastfm_candidates))
    anchor_token = _SEED_ANCHORS.set((seed_anchor,))
    mode_token = _SEED_MODE.set(request.seed_mode)
    try:
        result = await _generate(prompt, request.track_count, request.options)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=safe_error_message(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail="Playlist generation failed. Please try again.",
        ) from error
    finally:
        _SEED_MODE.reset(mode_token)
        _SEED_ANCHORS.reset(anchor_token)
        _SEED_RECOMMENDATIONS.reset(recommendation_token)

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
    result["seed_mode"] = request.seed_mode
    if isinstance(result.get("lastfm"), dict):
        _refresh_lastfm_selection(result["lastfm"], result["tracks"])
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
        "All explicit constraints in the original request remain mandatory. Do not relax "
        "dates, years, language, country, genre, exclusions or other limits when replacing "
        "the song.\n"
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
            track_identity_key(track.title, track.artists)
            for track in request.existing_tracks
        }
        existing_keys.add(track_identity_key(current.title, current.artists))
        for candidate in candidates:
            if candidate.get("video_id") in existing_ids:
                continue
            if track_identity_key(
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
