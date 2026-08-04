"""Metadata validation capacity and shared MusicBrainz request integration."""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import Any

import httpx

from backend.musicbrainz_client import rate_limited_get


def metadata_lookup_limit(candidate_count: int) -> int:
    """Validate every candidate unless an explicit administrator limit is set."""
    raw = os.getenv("METADATA_VALIDATION_MAX_LOOKUPS")
    if raw is None:
        return candidate_count
    try:
        return max(0, int(raw))
    except ValueError:
        return candidate_count


async def metadata_filter(
    candidates: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    from backend import youtube as module

    constraints = module.active_constraints()
    if not constraints.active:
        return list(candidates), []

    unique_candidates: list[dict[str, str]] = []
    seen_keys: set[str] = set()
    for candidate in candidates:
        key = module.track_identity_key(
            candidate.get("title", ""),
            candidate.get("artist", ""),
        )
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        unique_candidates.append(candidate)

    accepted: list[dict[str, str]] = []
    rejected: list[dict[str, Any]] = []
    remaining_lookups = metadata_lookup_limit(len(unique_candidates))
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(8.0),
        headers={
            "User-Agent": module.METADATA_USER_AGENT,
            "Accept": "application/json",
        },
    ) as client:
        for candidate in unique_candidates:
            artist = str(candidate.get("artist", "")).strip()
            title = str(candidate.get("title", "")).strip()
            cached = module._read_cache(artist, title)
            if cached is not None:
                result = module.validate_metadata(cached, constraints)
            elif remaining_lookups > 0:
                remaining_lookups -= 1
                result = await module.validate_candidate(
                    candidate,
                    constraints,
                    client=client,
                )
            else:
                result = module._budget_exceeded_result(candidate)

            if result.status == "valid":
                copy = dict(candidate)
                copy["metadata_validation"] = asdict(result.metadata)  # type: ignore[assignment]
                accepted.append(copy)
            else:
                rejected.append(module._metadata_rejection(candidate, result))
    return accepted, rejected


async def metadata_rate_limited_get(
    client: httpx.AsyncClient,
    params: dict[str, str],
) -> httpx.Response:
    from backend import metadata_validation as module

    return await rate_limited_get(
        client,
        f"{module.API_ROOT}/recording",
        params=params,
    )


async def search_artist(
    name: str,
    client: httpx.AsyncClient,
) -> dict[str, str] | None:
    from backend import entity_resolution as module

    cached = module._read_cache(name)
    if cached is not None:
        return cached or None
    response = await rate_limited_get(
        client,
        f"{module.API_ROOT}/artist",
        params={
            "query": f'artist:"{name}"',
            "fmt": "json",
            "limit": "5",
        },
    )
    response.raise_for_status()
    candidates = [
        item
        for item in response.json().get("artists", [])
        if isinstance(item, dict)
    ]
    expected = module._normalize(name)
    exact = [
        item
        for item in candidates
        if module._normalize(str(item.get("name", ""))) == expected
    ]
    matches = exact or candidates
    if not matches:
        module._write_cache(name, {})
        return None
    best = max(matches, key=lambda item: int(item.get("score", 0) or 0))
    score = int(best.get("score", 0) or 0)
    canonical = str(best.get("name", "")).strip()
    mbid = str(best.get("id", "")).strip()
    if score < module.MIN_API_SCORE or not canonical or not mbid:
        module._write_cache(name, {})
        return None
    result = {
        "input": name,
        "name": canonical,
        "mbid": mbid,
        "score": str(score),
    }
    module._write_cache(name, result)
    return result


async def verify_album_artist_pair(
    album: str,
    artist: str,
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    from backend import constraint_relationships as module

    cached = module._read_cache(album, artist)
    if cached is not None:
        return cached
    response = await rate_limited_get(
        client,
        f"{module.API_ROOT}/release-group",
        params={
            "query": f'releasegroup:"{album}" AND artist:"{artist}"',
            "fmt": "json",
            "limit": "8",
        },
    )
    response.raise_for_status()

    expected_album = module.normalize_identity(album)
    expected_artist = module.normalize_identity(artist)
    matches: list[dict[str, Any]] = []
    for item in response.json().get("release-groups", []):
        if not isinstance(item, dict):
            continue
        if int(item.get("score", 0) or 0) < module.MIN_API_SCORE:
            continue
        if module.normalize_identity(str(item.get("title", ""))) != expected_album:
            continue
        credited = module._artist_credit_names(item)
        if not any(
            module.normalize_identity(name) == expected_artist
            for name in credited
        ):
            continue
        matches.append(item)

    if not matches:
        result = {"album": album, "artist": artist, "matches": False}
        module._write_cache(album, artist, result)
        return result
    best = max(matches, key=lambda item: int(item.get("score", 0) or 0))
    result = {
        "album": str(best.get("title", album)).strip() or album,
        "artist": artist,
        "matches": True,
        "score": int(best.get("score", 0) or 0),
        "mbid": str(best.get("id", "")).strip() or None,
    }
    module._write_cache(album, artist, result)
    return result
