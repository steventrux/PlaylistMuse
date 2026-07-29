"""Playlist generation orchestration independent from HTTP routes."""

from __future__ import annotations

from backend.catalogs.base import MusicCatalog
from backend.catalogs.youtube_music import youtube_music_catalog
from backend.config import load_config
from backend.llm import generate_playlist_draft
from backend.schemas import PlaylistOptions

# Compatibility aliases retained for existing tests and integration patch points.
resolve_candidates = youtube_music_catalog.resolve_candidates
track_identity_key = youtube_music_catalog.track_identity_key


def _candidate_key(candidate: dict, identity_key) -> str:
    return identity_key(
        str(candidate.get("title", "")),
        str(candidate.get("artist", candidate.get("artists", ""))),
    )


def _replenishment_prompt(
    original_prompt: str,
    playlist_title: str,
    playlist_description: str,
    missing: int,
    pool_size: int,
    tracks: list[dict],
    attempted_candidates: list[dict],
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
    return (
        f"The original playlist request is:\n{original_prompt}\n\n"
        f"Playlist title: {playlist_title}\n"
        f"Playlist description: {playlist_description}\n"
        f"The playlist still needs {missing} resolvable songs. Suggest exactly "
        f"{pool_size} NEW replacement candidates that are likely to exist as normal "
        "song entries on YouTube Music. Use canonical released titles and mainstream "
        "artist spelling. Do not repeat any forbidden song.\n"
        f"Forbidden or already attempted songs:\n{forbidden or '- None'}"
    )


async def generate_playlist(
    prompt: str,
    count: int,
    options: PlaylistOptions,
    *,
    catalog: MusicCatalog | None = None,
    load_config_fn=None,
    generate_playlist_draft_fn=None,
    resolve_candidates_fn=None,
    track_identity_key_fn=None,
) -> dict:
    """Generate, resolve and replenish one playlist using the existing behaviour."""
    load_config_fn = load_config_fn or load_config
    generate_playlist_draft_fn = generate_playlist_draft_fn or generate_playlist_draft

    if catalog is None:
        resolve_candidates_fn = resolve_candidates_fn or resolve_candidates
        track_identity_key_fn = track_identity_key_fn or track_identity_key
    else:
        resolve_candidates_fn = resolve_candidates_fn or catalog.resolve_candidates
        track_identity_key_fn = track_identity_key_fn or catalog.track_identity_key

    config = load_config_fn()
    draft = await generate_playlist_draft_fn(config, prompt, count)
    exclusions = options.model_dump()
    tracks, unresolved = await resolve_candidates_fn(draft["tracks"], exclusions)

    attempted_candidates = list(draft["tracks"])
    attempted_keys = {
        _candidate_key(candidate, track_identity_key_fn)
        for candidate in attempted_candidates
    }
    resolved_keys = {
        track_identity_key_fn(track.get("title", ""), track.get("artists", ""))
        for track in tracks
    }
    resolved_ids = {track.get("video_id") for track in tracks if track.get("video_id")}
    stalled_rounds = 0

    for _round in range(1, 7):
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
        )
        refill = await generate_playlist_draft_fn(config, refill_prompt, pool_size)
        fresh_candidates: list[dict] = []
        for candidate in refill["tracks"]:
            key = _candidate_key(candidate, track_identity_key_fn)
            if not key or key in attempted_keys:
                continue
            attempted_keys.add(key)
            attempted_candidates.append(candidate)
            fresh_candidates.append(candidate)

        if not fresh_candidates:
            stalled_rounds += 1
            if stalled_rounds >= 2:
                break
            continue

        newly_resolved, newly_unresolved = await resolve_candidates_fn(
            fresh_candidates,
            exclusions,
        )
        unresolved.extend(newly_unresolved)
        added = 0
        for track in newly_resolved:
            track_key = track_identity_key_fn(
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
        if stalled_rounds >= 2:
            break

    if len(tracks) < count:
        raise ValueError(
            f"PlaylistMuse found only {len(tracks)} of {count} distinct tracks that "
            "could be verified on YouTube Music. Try a broader prompt or request "
            "fewer tracks."
        )

    return {
        "name": draft["title"],
        "description": draft["description"],
        "prompt": prompt,
        "requested_count": count,
        "resolved_count": count,
        "tracks": tracks[:count],
        "unresolved": unresolved,
    }
