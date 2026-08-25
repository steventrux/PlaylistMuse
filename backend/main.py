"""PlaylistMuse FastAPI application."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

from backend.config import (
    FALLBACK_FIELDS,
    AppConfig,
    api_key_matches_provider,
    api_key_slot,
    load_config,
    save_config,
)
from backend.constraint_interpreter import interpret_constraints
from backend.generation_counter import record_generation
from backend.generation_stage_timing import (
    record_stage_ms,
    reset_stage_timings,
    stage_timings_snapshot,
)
from backend.generation_errors import record_generation_error
from backend.generation_runtime import (
    _LAST_INTERPRETED_CONSTRAINTS,
    discover_for_seed as similar_track_candidates,
    generate_playlist_draft,
    resolve_candidates,
)
from backend.favorites import FavoritesRequestLevel
from backend.llm import safe_error_message
from backend.metadata_validation import extract_metadata_constraints
from backend.playlist_ordering import (
    chronological_order_from_payload,
    energy_order_from_payload,
    order_tracks_by_energy,
    order_tracks_by_release_date,
)
from backend.playlist_stats import compute_stats
from backend.prompt_analysis import analyze_prompt_semantics
from backend.telemetry import report_playlist_generated, telemetry_enabled
from backend.version import APP_VERSION, with_playlist_signature
from backend.youtube import search_songs, track_identity_key
from backend.youtube_routes import router as youtube_router

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
logger = logging.getLogger("playlistmuse.performance")

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
_GENERATION_PROGRESS: ContextVar[Callable[[str], None] | None] = ContextVar(
    "playlistmuse_generation_progress",
    default=None,
)

GENERATION_STAGE_MESSAGES = {
    "llm_initial": "Interpreting your request and drafting the playlist…",
    "catalogue_resolution_initial": "Validating tracks and resolving them on YouTube Music…",
    "llm_replenishment": "Refining the playlist to fill any gaps…",
    "catalogue_resolution_replenishment": "Validating the new tracks on YouTube Music…",
    "energy_ordering": "Analyzing sonic energy to order the playlist…",
}


def _emit_progress(stage: str) -> None:
    """Notify an in-flight streaming request of a generation-stage transition, if any.

    A plain no-op for every existing caller of _generate(): the callback is only ever set
    by the streaming endpoints below, via a ContextVar (same pattern as _SEED_MODE etc.)
    so _generate()'s signature never has to change.
    """
    callback = _GENERATION_PROGRESS.get()
    if callback is not None:
        callback(stage)


app = FastAPI(
    title="PlaylistMuse",
    description="AI-assisted playlist creation for YouTube Music",
    version=APP_VERSION,
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
            "energy, mood and era close to the seed, and stay within the seed's own "
            "subgenre and scene throughout -- do not drift into adjacent subgenres even "
            "if they share some Last.fm overlap. Do not add contrast tracks, broad genre "
            "neighbours or famous songs merely to create a journey. Variety and flow must "
            "never weaken similarity. If in doubt about a candidate, leave it out."
        )
    if mode == "exploratory":
        return (
            "EXPLORATORY seed mode: this must read as a real journey, not a repeat of the "
            "seed's exact subgenre track after track. Start close to the seed, then "
            "deliberately range further as the playlist progresses: pull in adjacent "
            "subgenres, different eras, and artists the seed influenced or was influenced "
            "by -- not just its closest sonic neighbours. Do not favor remixes or reworks "
            "as a way to add variety; the request's own exclude/include filters already "
            "govern recording versions -- use different songs and artists to create range, "
            "not different versions of the same recording. Roughly half the tracks or more "
            "should come from outside the seed's immediate subgenre. Every track must still "
            "connect through at least one concrete, statable characteristic (sound, rhythm, "
            "mood, instrumentation, scene or artist affinity) -- explain that link, don't "
            "just assert similarity. Avoid arbitrary contrast or songs with no defensible "
            "connection to the seed."
        )
    return (
        "BALANCED seed mode: keep the seed clearly central. Roughly two-thirds to three-"
        "quarters of tracks should be close matches supported by Last.fm or strong musical "
        "affinity; deliberately include a handful (roughly one-quarter to one-third) of "
        "compatible variations -- an adjacent subgenre, a different era, or a related "
        "artist -- rather than staying entirely within the seed's exact sound. Flow may "
        "organise the result but may not override similarity to the seed."
    )


def _seed_lastfm_evidence_params(mode: str, track_count: int) -> tuple[int, bool]:
    """Return (limit, broaden) for the seed's Last.fm evidence fetch, tuned per mode.

    Prompt wording alone wasn't enough to make the three seed modes feel meaningfully
    different (verified live, 2026-08-15): all three were fed the identical evidence pool,
    so the model had little reason to diversify even when instructed to. Strict now
    requests a tighter pool (Last.fm already returns matches ranked by score, so a smaller
    limit keeps only the closest ones); exploratory requests `broaden=True`, blending in
    related-artist signals for genuine breadth. This costs one extra Last.fm HTTP call for
    exploratory only (~0.7s, measured) -- balanced/strict are unaffected.
    """
    default_limit = min(MAX_LASTFM_CONTEXT_TRACKS, max(20, track_count * 2))
    if mode == "strict":
        return min(MAX_LASTFM_CONTEXT_TRACKS, max(10, track_count)), False
    if mode == "exploratory":
        return default_limit, True
    return default_limit, False


class SettingsResponse(BaseModel):
    provider: str
    model: str
    fallback_1: str
    fallback_2: str
    fallback_3: str
    fallback_4: str
    fallback_5: str
    fallback_6: str
    fallback_7: str
    fallback_8: str
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
    fallback_3: str = Field(default="", max_length=120)
    fallback_4: str = Field(default="", max_length=120)
    fallback_5: str = Field(default="", max_length=120)
    fallback_6: str = Field(default="", max_length=120)
    fallback_7: str = Field(default="", max_length=120)
    fallback_8: str = Field(default="", max_length=120)
    base_url: str = ""


class PlaylistOptions(BaseModel):
    exclude_live: bool = True
    exclude_covers: bool = True
    exclude_remixes: bool = True


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=1950)
    track_count: int = Field(default=25, ge=5, le=100)
    options: PlaylistOptions = Field(default_factory=PlaylistOptions)
    # The score already shown to the user by /api/prompts/analyze before they clicked
    # Generate -- not recomputed here, so recording it costs no extra AI call.
    complexity_score: int | None = Field(default=None, ge=0, le=100)

    @field_validator("prompt")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        return _normalize_prompt_text(value)


class PromptAnalysisRequest(GenerateRequest):
    pass


_DIMENSION_POINTS = {
    "genre": 3,
    "period": 3,
    "mood_energy": 3,
    "context": 2,
    "references": 2,
    "language_geography": 2,
    "popularity": 3,
    "sound": 3,
}
_STRUCTURE_POINTS = {
    "ordering": 4,
    "alternation": 7,
    "progression": 8,
    "proportions": 6,
    "transitions": 6,
    "sections": 7,
}


def _quantity_points(track_count: int) -> int:
    if track_count <= 15:
        return 0
    if track_count <= 30:
        return 3
    if track_count <= 50:
        return 7
    if track_count <= 100:
        return 11
    return 15


def _complexity_level(score: int) -> str:
    if score < 20:
        return "Simple"
    if score < 40:
        return "Detailed"
    if score < 65:
        return "Complex"
    if score < 85:
        return "Very complex"
    return "Extreme"


def _clarity_level(score: int) -> str:
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 55:
        return "Fair"
    return "Needs clarification"


_TEMPORAL_RANGE_POINTS = 20
_TEMPORAL_OPEN_POINTS = 8
_ARTIST_COUNTRY_POINTS = 3


def _energy_order_points(track_count: int) -> int:
    """Progressive weight matching the real measured ReccoBeats fetch cost per track count.

    A 2026-08-24 live spike measured ~1.6s per track, serialized behind ReccoBeats' global
    rate limit -- roughly 30-45s for a 20-25 track playlist, close to doubling the ~60-70s
    generation baseline. These brackets make that reference case land exactly at "Very
    complex" (see _complexity_level), scaling down for smaller requests and up to "Extreme"
    for larger ones, rather than a single flat weight that would misrepresent the real cost
    at very different playlist sizes.
    """
    if track_count <= 10:
        return 25
    if track_count <= 25:
        return 60
    if track_count <= 50:
        return 75
    return 90


def _performance_cost(prompt: str, track_count: int) -> tuple[int, list[str]]:
    """Points reflecting known extra catalogue-validation cost, not just semantic difficulty.

    Reuses extract_metadata_constraints and energy_order_from_payload's local regex
    fallback -- the same local, no-network heuristics that generation already falls back
    to -- so this adds no extra AI/network call and no extra latency to the live-typing
    complexity indicator. Only covers constraints with a currently measured or
    well-understood extra cost:
    - An exact release year, or a closed release-year range (from AND to), makes every
      candidate pay for a second MusicBrainz lookup unconditionally (see
      _historical_probe_cutoff in metadata_validation.py) -- directly measured at ~180s vs
      ~3s for 25 candidates in one real generation (roughly 60% of total generation time in
      that run). Weighted heavily relative to the semantic-complexity categories below, since
      this single factor can outweigh all of them combined in real wall-clock terms.
    - An open-ended release-year bound (only "from" or only "to") sometimes triggers the
      same second lookup, but only when the primary result doesn't already satisfy it.
    - An artist-country constraint adds one extra MusicBrainz artist lookup per new artist
      (cached 90 days, so cheap after the first use, but real on a cold cache).
    - An explicit sonic-energy ordering request requires one ReccoBeats audio-feature fetch
      per track, serialized behind a global rate limit -- see _energy_order_points for the
      measured cost this reflects.

    This is a heuristic on the raw prompt text, not the AI-verified constraint interpretation
    used at generation time -- it can occasionally miss an unusually-phrased constraint, or
    flag a phrase that turns out not to be one. It only affects the displayed complexity
    estimate, never actual generation behavior.
    """
    constraints = extract_metadata_constraints(prompt)
    points = 0
    reasons: list[str] = []

    if constraints.release_year is not None or (
        constraints.release_year_from is not None
        and constraints.release_year_to is not None
    ):
        points += _TEMPORAL_RANGE_POINTS
        reasons.append(
            "Release-year constraint: every candidate needs a second catalogue lookup "
            "to confirm the true original release date."
        )
    elif (
        constraints.release_year_from is not None
        or constraints.release_year_to is not None
    ):
        points += _TEMPORAL_OPEN_POINTS
        reasons.append(
            "Release-year constraint: some candidates may need an extra catalogue lookup."
        )

    if constraints.artist_country is not None:
        points += _ARTIST_COUNTRY_POINTS
        reasons.append(
            "Artist-origin constraint: new artists need an extra catalogue lookup "
            "(cached after the first use)."
        )

    if energy_order_from_payload(None, prompt) is not None:
        points += _energy_order_points(track_count)
        low_seconds = max(1, round(track_count * 1.2))
        high_seconds = max(low_seconds + 1, round(track_count * 2.0))
        reasons.append(
            "Sonic-energy ordering: every track needs an external audio-feature lookup, "
            "serialized behind a strict rate limit, adding roughly "
            f"{low_seconds}-{high_seconds} seconds for {track_count} tracks."
        )

    return points, reasons


def _score_prompt_analysis(analysis: dict, track_count: int, prompt: str) -> dict:
    dimensions = list(dict.fromkeys(analysis["dimensions"]))
    structures = list(dict.fromkeys(analysis["structures"]))
    hard_constraints = int(analysis["hard_constraints"])
    soft_constraints = int(analysis["soft_constraints"])
    relations = int(analysis["relations"])
    dimension_score = min(
        20, sum(_DIMENSION_POINTS.get(item, 0) for item in dimensions)
    )
    constraint_score = min(25, (4 * hard_constraints) + (2 * soft_constraints))
    structure_score = min(
        25, sum(_STRUCTURE_POINTS.get(item, 0) for item in structures)
    )
    relation_score = min(15, 3 * relations)
    performance_points, performance_notes = _performance_cost(prompt, track_count)
    score = min(
        100,
        5
        + dimension_score
        + constraint_score
        + structure_score
        + relation_score
        + _quantity_points(track_count)
        + performance_points,
    )

    ambiguities = analysis["ambiguities"]
    conflicts = analysis["conflicts"]
    missing = analysis["missing_information"]
    imprecisions = analysis["imprecisions"]
    typos = analysis["possible_typos"]
    clarity = max(
        0,
        100
        - (10 * len(ambiguities))
        - (25 * len(conflicts))
        - (15 * len(missing))
        - (5 * len(imprecisions))
        - (5 * len(typos)),
    )
    issues = list(
        dict.fromkeys([*conflicts, *ambiguities, *missing, *imprecisions, *typos])
    )
    return {
        "score": score,
        "level": _complexity_level(score),
        "clarity": clarity,
        "clarity_level": _clarity_level(clarity),
        "dimensions": len(dimensions),
        "hard_constraints": hard_constraints,
        "soft_constraints": soft_constraints,
        "structures": len(structures),
        "relations": relations,
        "issues": issues,
        "performance_notes": performance_notes,
    }


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


class JourneyGenerateRequest(BaseModel):
    start: SeedTrack
    end: SeedTrack
    track_count: int = Field(default=25, ge=5, le=100)
    options: PlaylistOptions = Field(default_factory=PlaylistOptions)

    @model_validator(mode="after")
    def _different_anchors(self) -> JourneyGenerateRequest:
        start_key = track_identity_key(self.start.title, self.start.artists)
        end_key = track_identity_key(self.end.title, self.end.artists)
        if start_key == end_key:
            raise ValueError(
                "Choose two different tracks for the start and end of the journey."
            )
        return self


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
        fallback_3=config.fallback_3,
        fallback_4=config.fallback_4,
        fallback_5=config.fallback_5,
        fallback_6=config.fallback_6,
        fallback_7=config.fallback_7,
        fallback_8=config.fallback_8,
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


def _increment_counter(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def _metadata_reason_labels(
    item: dict[str, Any],
    *,
    temporal_required: bool,
    artist_country_required: bool,
) -> set[str]:
    validation = item.get("metadata_validation")
    if not isinstance(validation, dict):
        return set()

    labels: set[str] = set()
    violations = validation.get("violations")
    if isinstance(violations, list):
        for violation in violations:
            text = str(violation).casefold()
            if "release year" in text:
                labels.add("release_year")
            elif "artist country" in text:
                labels.add("artist_country")
            elif "album" in text:
                labels.add("album")
            elif "artist" in text:
                labels.add("artist")
            else:
                labels.add("metadata_violation")

    warnings = validation.get("warnings")
    if isinstance(warnings, list):
        for warning in warnings:
            text = str(warning).casefold()
            if "no musicbrainz match" in text:
                labels.add("no_musicbrainz_match")
            elif "match confidence is too low" in text:
                labels.add("low_musicbrainz_confidence")
            elif "lookup budget exceeded" in text:
                labels.add("lookup_budget")
            elif "metadata lookup unavailable" in text:
                labels.add("metadata_service_unavailable")

    status = str(validation.get("status", "")).strip().casefold()
    if not labels and status == "unknown":
        if temporal_required and validation.get("original_release_year") is None:
            labels.add("missing_release_year")
        if artist_country_required and not validation.get("artist_country"):
            labels.add("missing_artist_country")
        if not labels:
            labels.add("metadata_unknown")
    elif not labels and status:
        labels.add(f"metadata_{status}")
    return labels


def _log_catalogue_diagnostics(
    stage: str,
    candidates: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
    *,
    accepted: int | None = None,
    playlist_before: int = 0,
) -> None:
    from backend.metadata_validation import active_constraints

    constraints = active_constraints()
    temporal_required = any(
        value is not None
        for value in (
            constraints.release_year,
            constraints.release_year_from,
            constraints.release_year_to,
        )
    )
    artist_country_required = constraints.artist_country is not None
    unresolved_reasons: dict[str, int] = {}
    metadata_reasons: dict[str, int] = {}

    for item in unresolved:
        if not isinstance(item, dict):
            _increment_counter(unresolved_reasons, "unknown")
            continue
        validation = item.get("metadata_validation")
        reason = str(item.get("unresolved_reason") or "").strip()
        if isinstance(validation, dict):
            _increment_counter(
                unresolved_reasons,
                reason or "metadata_validation",
            )
            for label in _metadata_reason_labels(
                item,
                temporal_required=temporal_required,
                artist_country_required=artist_country_required,
            ):
                _increment_counter(metadata_reasons, label)
        elif reason:
            _increment_counter(unresolved_reasons, reason)
        else:
            _increment_counter(unresolved_reasons, "youtube_resolution")

    logger.info(
        "catalogue_diagnostics stage=%s candidates=%s selected=%s accepted=%s "
        "playlist_before=%s unresolved=%s unresolved_reasons=%s metadata_reasons=%s",
        stage,
        len(candidates),
        len(selected),
        len(selected) if accepted is None else accepted,
        playlist_before,
        len(unresolved),
        dict(sorted(unresolved_reasons.items())),
        dict(sorted(metadata_reasons.items())),
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


def _seed_evidence_guidance(candidates: list[dict[str, str]], *, seed_mode: str) -> str:
    """Fold Last.fm seed/anchor evidence directly into the single initial draft prompt.

    Seed and journey requests always have real Last.fm-derived candidates before any draft
    exists (unlike prompt-based generation, whose lastfm_candidates is always empty -- see
    discover_from_anchors's deliberate no-op in lastfm_discovery.py). Folding the evidence
    into the one llm_initial draft, instead of running a second llm_guided draft
    afterwards, removes an entire redundant LLM generation pass (with its own quota-repair
    and creative-repair rounds) for every such request.
    """
    evidence = "\n".join(
        f"- {candidate.get('artist', 'Unknown artist')} — "
        f"{candidate.get('title', 'Unknown track')} "
        f"[{candidate.get('lastfm_strategy', 'lastfm')}]"
        for candidate in candidates[:MAX_LASTFM_CONTEXT_TRACKS]
    )
    seed_instruction = f"\n{_seed_mode_instruction(seed_mode)}\n" if seed_mode else ""
    mode_clause = " and the selected seed mode" if seed_mode else ""
    return (
        f"{seed_instruction}\n"
        "Last.fm collaborative-listening evidence:\n"
        f"{evidence or '- None'}\n\n"
        f"Use this evidence only when it satisfies the original request{mode_clause}. "
        "You may also select tracks not listed above when they satisfy every "
        "mandatory constraint and have a clear musical justification. Do not mechanically "
        "copy the evidence list; use your own musical judgment. For every selected song, "
        "write a natural song description and a playlist-specific reason. Use canonical "
        "artist and released track names."
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


def _favorites_weight_instruction(*, level: FavoritesRequestLevel, noun: str) -> str:
    if level is FavoritesRequestLevel.EXPLICIT:
        return (
            f"The user explicitly asked to use their favorite {noun} in this request. "
            f"Treat these {noun} as a strong, primary preference: actively include as "
            f"many of them (or songs musically similar to them) as you can while still "
            f"satisfying every mandatory constraint, exclusion and quantity in the "
            f"request -- do not merely use them as a tie-breaker between otherwise-equal "
            f"candidates."
        )
    if level is FavoritesRequestLevel.INSPIRED:
        return (
            f"The user asked for a playlist inspired by their favorite {noun}. Treat "
            f"these {noun} as a moderately strong bias -- noticeably more influential "
            f"than a default tie-breaker: lean toward including them, or songs/artists "
            f"musically similar to them, more often than not. This is not an exclusive "
            f"list, so keep bringing in other well-fitting suggestions too, and never "
            f"let this bias override an explicit constraint, exclusion or quantity in "
            f"the request."
        )
    return (
        f"Treat these {noun} as a soft, secondary bias only: never override an "
        f"explicit constraint, exclusion or quantity in the request to include them, "
        f"and never force one in if it does not fit this specific request. When "
        f"multiple otherwise-equal candidates are available, mildly prefer these "
        f"{noun} or musically similar ones."
    )


def _favorites_guidance(
    *,
    artists_level: FavoritesRequestLevel | None = None,
    tracks_level: FavoritesRequestLevel | None = None,
) -> str:
    """Fold the user's bookmarked favorites into the prompt as generation guidance.

    Reads the small local favorites.json once per request (same cost class as
    load_config()) -- no network call, no per-request caching needed at this scale.
    """
    from backend.favorites import favorite_artist_names, favorite_track_summaries

    artists_level = artists_level or FavoritesRequestLevel.NONE
    tracks_level = tracks_level or FavoritesRequestLevel.NONE
    artists = favorite_artist_names(limit=40)
    tracks = favorite_track_summaries(limit=40)
    if not artists and not tracks:
        return ""

    artist_lines = "\n".join(f"- {name}" for name in artists)
    track_lines = "\n".join(f"- {t['artists']} — {t['title']}" for t in tracks)
    return (
        "\n\nUser's favorite artists and tracks (bookmarked by the listener).\n"
        f"{_favorites_weight_instruction(level=artists_level, noun='artists')}\n"
        f"Favorite artists:\n{artist_lines or '- None'}\n"
        f"{_favorites_weight_instruction(level=tracks_level, noun='tracks')}\n"
        f"Favorite tracks:\n{track_lines or '- None'}"
    )


def _seed_favorite_tracks(options: PlaylistOptions, limit: int) -> list[dict]:
    """Return bookmarked favorite tracks as ready-made playlist entries.

    Favorite tracks are already-resolved (real video_id, saved when the user
    bookmarked them), so this bypasses the usual AI-suggest-then-catalogue-resolve
    flow entirely -- re-resolving by title/artist search risks silently swapping in
    a different recording than the one actually bookmarked.
    """
    from backend.favorites import list_favorite_tracks
    from backend.recording_variants import track_matches_variant

    seeded: list[dict] = []
    for entry in list_favorite_tracks():
        if options.exclude_live and track_matches_variant(entry, "live"):
            continue
        if options.exclude_covers and track_matches_variant(entry, "cover"):
            continue
        if options.exclude_remixes and track_matches_variant(entry, "remix"):
            continue
        video_id = entry.get("video_id", "")
        if not video_id:
            continue
        seeded.append(
            {
                "video_id": video_id,
                "title": entry.get("title", ""),
                "artists": entry.get("artists", ""),
                "album": entry.get("album") or None,
                "thumbnail_url": entry.get("thumbnail_url", ""),
                "url": f"https://music.youtube.com/watch?v={video_id}",
                "description": "",
                "reason": "Bookmarked favorite.",
            }
        )
        if len(seeded) >= limit:
            break
    return seeded


def _initial_draft_overshoot(count: int) -> int:
    """Extra tracks to request in the very first draft, beyond the target `count`.

    Every replenishment round after the first already over-requests based on assumed
    catalogue-resolution yield (`_optimized_replenishment_request`), but the initial draft
    asked for exactly `count` with no safety margin -- so any request that loses even a
    few candidates to resolution failure fell straight into a full extra LLM +
    catalogue-resolution round trip. The replenishment loop's own exit condition
    (`missing = count - len(tracks)`) and the final `tracks[:count]` truncation already
    handle an over-sized result for free, so this costs nothing beyond a marginally
    longer prompt on the same single initial call.
    """
    return min(8, max(3, round(count * 0.15)))


async def _generate(prompt: str, count: int, options: PlaylistOptions) -> dict:
    config = load_config()
    seed_mode = _SEED_MODE.get()
    lastfm_anchors = list(_SEED_ANCHORS.get())
    lastfm_candidates = list(_SEED_RECOMMENDATIONS.get())

    from backend.favorites import (
        MAX_FAVORITE_ARTISTS,
        activate_favorite_artist_allowlist,
        favorite_artist_names,
        favorite_categories_requested_levels,
    )

    artists_level, tracks_level = favorite_categories_requested_levels(prompt)
    explicit_artists = artists_level is FavoritesRequestLevel.EXPLICIT
    explicit_tracks = tracks_level is FavoritesRequestLevel.EXPLICIT
    activate_favorite_artist_allowlist(
        favorite_artist_names(limit=MAX_FAVORITE_ARTISTS) if explicit_artists else []
    )
    favorites_guidance = _favorites_guidance(artists_level=artists_level, tracks_level=tracks_level)
    initial_prompt = _constraint_priority_prompt(prompt)
    if lastfm_candidates:
        initial_prompt += _seed_evidence_guidance(lastfm_candidates, seed_mode=seed_mode)
    initial_prompt += favorites_guidance
    exclusions = options.model_dump()

    tracks = _seed_favorite_tracks(options, limit=count) if explicit_tracks else []
    # A pure "only my favorite tracks" request must never pad with AI suggestions --
    # the AI is skipped entirely rather than asked for candidates that would only be
    # discarded (see the allow_shortfall guard below for the matching count relaxation).
    skip_initial_ai = explicit_tracks and not explicit_artists
    missing_after_seed = count - len(tracks)
    guidance_applied = bool(lastfm_candidates)

    if skip_initial_ai or missing_after_seed <= 0:
        draft = {
            "title": "Your Favorite Tracks",
            "description": "A playlist built from your bookmarked favorite tracks.",
        }
        draft_tracks: list[dict] = []
        unresolved: list[dict] = []
        attempted_candidates: list[dict] = []
        attempted_keys: set[str] = set()
    else:
        _emit_progress("llm_initial")
        draft = await generate_playlist_draft(
            config,
            initial_prompt,
            missing_after_seed + _initial_draft_overshoot(missing_after_seed),
            is_seed_generation=bool(lastfm_anchors),
        )
        draft_tracks = _annotate_lastfm_sources(
            list(draft.get("tracks", [])),
            lastfm_candidates,
        )
        _emit_progress("catalogue_resolution_initial")
        newly_resolved, unresolved = await resolve_candidates(draft_tracks, exclusions)
        seeded_ids = {track["video_id"] for track in tracks}
        tracks += [
            track for track in newly_resolved if track.get("video_id") not in seeded_ids
        ]
        attempted_candidates = list(draft_tracks)
        attempted_keys = {_candidate_key(candidate) for candidate in attempted_candidates}

    _log_catalogue_diagnostics(
        "initial",
        draft_tracks,
        tracks,
        unresolved,
        playlist_before=0,
    )

    resolved_keys = {
        track_identity_key(track.get("title", ""), track.get("artists", ""))
        for track in tracks
    }
    resolved_ids = {track.get("video_id") for track in tracks if track.get("video_id")}

    from backend.creative_intent import active_creative_intent

    # A hard-restricted favorite-artist pool (see backend.favorites) combined with an
    # explicit mood/style requirement may simply have no matching tracks among those
    # few artists -- every replenishment round would just retry the same impossible
    # request against a real (often slow) AI call, so give up after one empty round
    # instead of exhausting the full replenishment budget on an unwinnable request.
    favorite_artist_creative_conflict = explicit_artists and bool(
        active_creative_intent().requirements
    )
    stall_limit = 1 if favorite_artist_creative_conflict else MAX_STALLED_ROUNDS

    stalled_rounds = 0
    for round_index in range(MAX_REPLENISHMENT_ROUNDS):
        if skip_initial_ai:
            break
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
        refill_prompt += favorites_guidance
        _emit_progress("llm_replenishment")
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
            if stalled_rounds >= stall_limit:
                break
            continue

        playlist_before = len(tracks)
        _emit_progress("catalogue_resolution_replenishment")
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

        _log_catalogue_diagnostics(
            f"replenishment_{round_index + 1}",
            fresh_candidates,
            newly_resolved,
            newly_unresolved,
            accepted=added,
            playlist_before=playlist_before,
        )
        stalled_rounds = 0 if added else stalled_rounds + 1
        if stalled_rounds >= stall_limit:
            break

    # A hard-restricted favorite-artist pool (see backend.favorites) combined with an
    # explicit mood/style requirement may simply have no matching tracks among those
    # few artists -- a shortfall (or, if nothing matches at all, a clear error) is the
    # honest outcome, not padding the count with genre-incompatible picks.
    allow_shortfall = (
        explicit_tracks and not explicit_artists
    ) or favorite_artist_creative_conflict
    if explicit_tracks and not explicit_artists and not tracks:
        raise ValueError(
            "You asked for your favorite tracks, but you haven't bookmarked any yet."
        )
    if favorite_artist_creative_conflict and not tracks:
        raise ValueError(
            "None of your favorite artists have tracks matching what you asked for "
            "in this request, so PlaylistMuse could not build this playlist. Try a "
            "different style/mood, or drop the favorite-artists request."
        )
    if len(tracks) < count and not allow_shortfall:
        raise ValueError(
            f"PlaylistMuse found only {len(tracks)} of {count} distinct tracks that "
            "could be verified on YouTube Music without deliberately relaxing the "
            "request. Try a broader prompt or request fewer tracks."
        )

    from backend.policy_enforcement import _ACTIVE_POLICY, apply_track_positions

    final_tracks = tracks[:count]
    active_policy = _ACTIVE_POLICY.get()
    if active_policy is not None:
        final_tracks = apply_track_positions(final_tracks, active_policy)

    interpretation = _LAST_INTERPRETED_CONSTRAINTS.get()
    if interpretation is None:
        interpretation = await interpret_constraints(config, prompt)
    chronological_order = chronological_order_from_payload(interpretation, prompt)
    energy_order = energy_order_from_payload(interpretation, prompt)

    if energy_order is None and chronological_order is not None:
        ordered_tracks = await order_tracks_by_release_date(
            final_tracks,
            chronological_order,
        )
        if active_policy is not None and active_policy.track_positions:
            positioned = apply_track_positions(ordered_tracks, active_policy)
            ordered_keys = [
                track_identity_key(track.get("title", ""), track.get("artists", ""))
                for track in ordered_tracks
            ]
            positioned_keys = [
                track_identity_key(track.get("title", ""), track.get("artists", ""))
                for track in positioned
            ]
            if positioned_keys != ordered_keys:
                raise ValueError(
                    "The requested chronological ordering conflicts with an explicit track position."
                )
        final_tracks = ordered_tracks
    elif energy_order is not None:
        _emit_progress("energy_ordering")
        chronological_for_energy = chronological_order if energy_order != "steady" else None
        energy_started_at = time.perf_counter()
        ordered_tracks = await order_tracks_by_energy(
            final_tracks,
            energy_order,
            chronological_direction=chronological_for_energy,
        )
        record_stage_ms(
            "energy_ordering", (time.perf_counter() - energy_started_at) * 1000
        )
        if active_policy is not None and active_policy.track_positions:
            positioned = apply_track_positions(ordered_tracks, active_policy)
            ordered_keys = [
                track_identity_key(track.get("title", ""), track.get("artists", ""))
                for track in ordered_tracks
            ]
            positioned_keys = [
                track_identity_key(track.get("title", ""), track.get("artists", ""))
                for track in positioned
            ]
            if positioned_keys != ordered_keys:
                raise ValueError(
                    "The requested energy ordering conflicts with an explicit track position."
                )
        final_tracks = ordered_tracks

    return {
        "name": draft["title"],
        "description": with_playlist_signature(draft["description"]),
        "prompt": prompt,
        "requested_count": count,
        "resolved_count": len(final_tracks),
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


@app.get("/api/stats")
async def get_stats() -> dict:
    """Local-only aggregate statistics -- nothing here is sent anywhere."""
    return compute_stats()


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
    fallbacks = {name: getattr(request, name).strip() for name in FALLBACK_FIELDS}
    base_url = request.base_url.strip()
    if request.provider in OPENROUTER_MODELS:
        model = OPENROUTER_MODELS[request.provider]
        fallbacks = dict.fromkeys(FALLBACK_FIELDS, "")
        base_url = ""

    config = AppConfig(
        provider=request.provider,
        api_key=active_key,
        model=model,
        **fallbacks,
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


async def _generate_with_telemetry(
    work: Callable[[], Any], *, complexity_score: int | None = None
) -> dict:
    """Time one top-level generation, record it, and tag the result with which
    provider produced it.

    Wraps `_generate()`/`_generate_from_seed_playlist()` at the route boundary (not
    inside `_generate()` itself) because seed-mode generation can call `_generate()`
    internally more than once per user-facing request (`_anchored_other_tracks()` retries
    once if the AI reproduces an anchor track) -- hooking inside `_generate()` would
    double-count those retries as separate playlists.
    """
    reset_stage_timings()
    started = time.perf_counter()
    result = await work()
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    result["generation_meta"] = {
        "provider": load_config().stats_key,
        "duration_ms": elapsed_ms,
        "stage_timings_ms": stage_timings_snapshot(),
        "complexity_score": complexity_score,
    }
    record_generation()
    if telemetry_enabled():
        asyncio.create_task(report_playlist_generated())
    return result


@app.post("/api/playlists/generate")
async def generate_playlist(request: GenerateRequest) -> dict:
    try:
        return await _generate_with_telemetry(
            lambda: _generate(request.prompt, request.track_count, request.options),
            complexity_score=request.complexity_score,
        )
    except ValueError as error:
        record_generation_error(error, provider=load_config().stats_key)
        raise HTTPException(status_code=400, detail=safe_error_message(error)) from error
    except Exception as error:
        record_generation_error(error, provider=load_config().stats_key)
        raise HTTPException(
            status_code=502,
            detail="Playlist generation failed. Please try again.",
        ) from error


@app.post("/api/prompts/analyze")
async def analyze_prompt(request: PromptAnalysisRequest) -> dict:
    try:
        semantics = await analyze_prompt_semantics(
            load_config(),
            request.prompt,
            track_count=request.track_count,
            options=request.options.model_dump(),
        )
        return _score_prompt_analysis(semantics, request.track_count, request.prompt)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=safe_error_message(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail="Prompt analysis failed. Please try again.",
        ) from error


def _is_anchor_track(
    track: dict, anchors: list[SeedTrack], anchor_keys: set[str]
) -> dict | None:
    video_ids = {anchor.video_id for anchor in anchors}
    if track.get("video_id") in video_ids:
        return track
    key = track_identity_key(track.get("title", ""), track.get("artists", ""))
    return track if key in anchor_keys else None


async def _anchored_other_tracks(
    prompt: str,
    other_count: int,
    options: PlaylistOptions,
    anchors: list[SeedTrack],
) -> tuple[dict, dict | None]:
    """Ask _generate() for exactly `other_count` tracks distinct from every anchor.

    Generalizes the original single-seed retry helper to an arbitrary number of anchor
    tracks so the same retry-once-forbidding-anchors logic serves both single-seed
    generation (one anchor) and two-anchor journey generation (start + end) without
    duplicating it. _generate() itself guarantees exactly `other_count` verified,
    quota-checked tracks; the only way this can fall short is if the AI independently
    reproduces an anchor among its own suggestions, retried once with all anchors
    explicitly forbidden.
    """
    anchor_keys = {track_identity_key(a.title, a.artists) for a in anchors}
    attempt_prompt = prompt
    reproduced_track: dict | None = None
    for _ in range(2):
        result = await _generate(attempt_prompt, other_count, options)
        match = next(
            (
                track
                for track in result["tracks"]
                if _is_anchor_track(track, anchors, anchor_keys) is not None
            ),
            None,
        )
        if match is None:
            return result, reproduced_track
        reproduced_track = reproduced_track or match
        forbidden = "; ".join(f"'{a.title}' by {a.artists}" for a in anchors)
        attempt_prompt = (
            f"{prompt}\n\nDo not include {forbidden} among your suggestions -- they are "
            "already placed elsewhere in the playlist."
        )
    names = " and ".join(f"'{a.title}' by {a.artists}" for a in anchors)
    raise ValueError(
        f"PlaylistMuse could not find enough tracks distinct from {names}. "
        "Try different tracks or request more tracks."
    )


async def _generate_from_seed_playlist(request: SeedGenerateRequest) -> dict:
    """Build a seed-anchored playlist. Raises ValueError/Exception like _generate() itself.

    Extracted from the generate-from-seed endpoint (pure refactor, no behavior change) so
    both the plain JSON endpoint and the streaming endpoint below can share it.
    """
    seed = request.seed
    other_count = request.track_count - 1
    prompt = (
        f"Create a playlist from the seed song '{seed.title}' by {seed.artists}. "
        f"{_seed_mode_instruction(request.seed_mode)} The seed must remain the primary "
        "reference for every selection. Do not let editorial sequencing or a narrative "
        "journey override the selected similarity mode. Do not include "
        f"'{seed.title}' by {seed.artists} itself among your suggestions -- it is "
        "already the playlist's first track; suggest only other songs related to it."
    )
    lastfm_limit, lastfm_broaden = _seed_lastfm_evidence_params(
        request.seed_mode, request.track_count
    )
    lastfm_candidates = await similar_track_candidates(
        seed.artists,
        seed.title,
        limit=lastfm_limit,
        broaden=lastfm_broaden,
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
        result, reproduced_track = await _anchored_other_tracks(
            prompt, other_count, request.options, [seed]
        )
    finally:
        _SEED_MODE.reset(mode_token)
        _SEED_ANCHORS.reset(anchor_token)
        _SEED_RECOMMENDATIONS.reset(recommendation_token)

    seed_payload = seed.model_dump()
    # The seed is a user-chosen reference track, not a generated suggestion: it always
    # appears first regardless of exclude_live/exclude_covers/exclude_remixes -- it is
    # deliberately never routed through resolve_candidates()'s exclusion filters.
    seed_payload["description"] = (
        (reproduced_track or {}).get("description")
        or "The reference song that establishes the playlist's core sound, mood and energy."
    )
    seed_payload["reason"] = (
        (reproduced_track or {}).get("reason")
        or "It anchors the sequence because every other selection was chosen in response to its musical character."
    )

    result["tracks"] = [seed_payload, *result["tracks"]]
    result["resolved_count"] = len(result["tracks"])
    result["seed"] = seed_payload
    result["seed_mode"] = request.seed_mode
    if isinstance(result.get("lastfm"), dict):
        _refresh_lastfm_selection(result["lastfm"], result["tracks"])
    return result


def _journey_instruction(start: SeedTrack, end: SeedTrack, bridge_count: int) -> str:
    return (
        f"Build a playlist that creates a sensible musical journey from the starting "
        f"song '{start.title}' by {start.artists} to the ending song '{end.title}' by "
        f"{end.artists}. Select {bridge_count} songs that form a deliberate step-by-step "
        "bridge between them: each song must connect musically to its neighbors through "
        "sound, instrumentation, energy, mood, scene, or artist affinity, gradually "
        "moving the listener from the starting song's sound toward the ending song's "
        "sound. Do not just pick songs similar to the start or end in isolation; the "
        "sequence as a whole must read as one coherent path. In each song's reason, "
        "explain concretely how it bridges from the previous step toward the next. Do "
        f"not include '{start.title}' by {start.artists} or '{end.title}' by "
        f"{end.artists} among your suggestions -- they are already placed as the first "
        "and last track."
    )


def _merge_journey_evidence(
    start_evidence: list[dict[str, str]],
    end_evidence: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Combine both anchors' Last.fm evidence into one deduplicated pool."""
    seen: set[str] = set()
    merged: list[dict[str, str]] = []
    for candidate in [*start_evidence, *end_evidence]:
        key = _candidate_key(candidate)
        if key and key not in seen:
            seen.add(key)
            merged.append(candidate)
    return merged


async def _generate_from_journey_playlist(request: JourneyGenerateRequest) -> dict:
    """Build a two-anchor journey playlist. Raises ValueError/Exception like _generate() itself."""
    start, end = request.start, request.end
    bridge_count = request.track_count - 2
    prompt = _journey_instruction(start, end, bridge_count)

    limit = min(MAX_LASTFM_CONTEXT_TRACKS, max(20, request.track_count * 2))
    start_evidence, end_evidence = await asyncio.gather(
        similar_track_candidates(start.artists, start.title, limit=limit),
        similar_track_candidates(end.artists, end.title, limit=limit),
    )
    lastfm_candidates = _merge_journey_evidence(start_evidence, end_evidence)
    anchors = (
        {"artist": start.artists, "title": start.title, "kind": "journey_start"},
        {"artist": end.artists, "title": end.title, "kind": "journey_end"},
    )
    recommendation_token = _SEED_RECOMMENDATIONS.set(tuple(lastfm_candidates))
    anchor_token = _SEED_ANCHORS.set(anchors)
    mode_token = _SEED_MODE.set("")
    try:
        result, _reproduced = await _anchored_other_tracks(
            prompt, bridge_count, request.options, [start, end]
        )
    finally:
        _SEED_MODE.reset(mode_token)
        _SEED_ANCHORS.reset(anchor_token)
        _SEED_RECOMMENDATIONS.reset(recommendation_token)

    # Both anchors are user-chosen reference tracks, not generated suggestions: they
    # always appear first/last regardless of exclude_live/exclude_covers/exclude_remixes,
    # deliberately never routed through resolve_candidates()'s exclusion filters -- same
    # treatment as the single seed in _generate_from_seed_playlist.
    start_payload = start.model_dump()
    start_payload["description"] = "The starting song that opens this musical journey."
    start_payload["reason"] = (
        "It anchors the beginning of the path; every following track bridges toward "
        "the ending song."
    )
    end_payload = end.model_dump()
    end_payload["description"] = "The ending song that completes this musical journey."
    end_payload["reason"] = (
        "It anchors the end of the path; every previous track bridged toward this "
        "destination."
    )

    result["tracks"] = [start_payload, *result["tracks"], end_payload]
    result["resolved_count"] = len(result["tracks"])
    result["journey"] = {"start": start_payload, "end": end_payload}
    if isinstance(result.get("lastfm"), dict):
        _refresh_lastfm_selection(result["lastfm"], result["tracks"])
    return result


@app.post("/api/playlists/generate-from-seed")
async def generate_from_seed(request: SeedGenerateRequest) -> dict:
    try:
        return await _generate_with_telemetry(
            lambda: _generate_from_seed_playlist(request)
        )
    except ValueError as error:
        record_generation_error(error, provider=load_config().stats_key)
        raise HTTPException(status_code=400, detail=safe_error_message(error)) from error
    except Exception as error:
        record_generation_error(error, provider=load_config().stats_key)
        raise HTTPException(
            status_code=502,
            detail="Playlist generation failed. Please try again.",
        ) from error


def _sse_event(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload)}\n\n".encode()


async def _stream_generation(
    work: Callable[[], Any],
) -> AsyncIterator[bytes]:
    """Run `work()` in the background, streaming SSE progress events as it advances.

    `work` is a zero-argument callable returning the generation coroutine (either
    `_generate(...)` or `_generate_from_seed_playlist(...)`). The progress callback is set
    on `_GENERATION_PROGRESS` here, before the background task is created, so the task's
    copy of the context (asyncio.Task snapshots the current context at creation time) sees
    it -- _generate() itself never needs a callback parameter.
    """
    queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
    last_stage: dict[str, str | None] = {"key": None, "message": None}

    def on_progress(stage: str) -> None:
        message = GENERATION_STAGE_MESSAGES.get(stage)
        if message:
            last_stage["key"] = stage
            last_stage["message"] = message
            queue.put_nowait(("stage", {"stage": stage, "message": message}))

    async def run() -> None:
        try:
            result = await work()
            await queue.put(("result", {"playlist": result}))
        except ValueError as error:
            record_generation_error(error, provider=load_config().stats_key)
            await queue.put((
                "error",
                {
                    "stage": last_stage["key"],
                    "stage_message": last_stage["message"],
                    "message": safe_error_message(error),
                },
            ))
        except Exception as error:  # noqa: BLE001 - translated into one safe SSE error event.
            record_generation_error(error, provider=load_config().stats_key)
            await queue.put((
                "error",
                {
                    "stage": last_stage["key"],
                    "stage_message": last_stage["message"],
                    "message": "Playlist generation failed. Please try again.",
                },
            ))

    token = _GENERATION_PROGRESS.set(on_progress)
    task = asyncio.ensure_future(run())
    try:
        while True:
            kind, payload = await queue.get()
            yield _sse_event({"type": kind, **payload})
            if kind in ("result", "error"):
                break
    finally:
        _GENERATION_PROGRESS.reset(token)
        if not task.done():
            task.cancel()


_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@app.post("/api/playlists/generate/stream")
async def generate_playlist_stream(request: GenerateRequest) -> StreamingResponse:
    return StreamingResponse(
        _stream_generation(
            lambda: _generate_with_telemetry(
                lambda: _generate(request.prompt, request.track_count, request.options),
                complexity_score=request.complexity_score,
            )
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@app.post("/api/playlists/generate-from-seed/stream")
async def generate_from_seed_stream(request: SeedGenerateRequest) -> StreamingResponse:
    return StreamingResponse(
        _stream_generation(
            lambda: _generate_with_telemetry(
                lambda: _generate_from_seed_playlist(request)
            )
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


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
    from backend.favorites import (
        MAX_FAVORITE_ARTISTS,
        activate_favorite_artist_allowlist,
        favorite_artist_names,
        favorite_categories_requested_levels,
    )

    replace_artists_level, replace_tracks_level = favorite_categories_requested_levels(
        request.prompt
    )
    replace_explicit_artists = replace_artists_level is FavoritesRequestLevel.EXPLICIT
    activate_favorite_artist_allowlist(
        favorite_artist_names(limit=MAX_FAVORITE_ARTISTS) if replace_explicit_artists else []
    )
    replacement_prompt += _favorites_guidance(
        artists_level=replace_artists_level, tracks_level=replace_tracks_level
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


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    return FileResponse(
        FRONTEND / "playlistmuse-favicon.png",
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html", headers={"Cache-Control": "no-cache"})
