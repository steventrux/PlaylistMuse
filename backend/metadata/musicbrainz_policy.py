"""Policy-aware MusicBrainz ranking driven by PlaylistMuse exclusion options."""

from __future__ import annotations

import re
from typing import Any, Mapping

from backend.metadata.musicbrainz import (
    MATCH_THRESHOLD,
    MusicBrainzClient,
    _candidate_payload,
    _rate_limited_get,
    build_recording_query,
)
from backend.metadata.musicbrainz_relations import (
    enrich_match_with_relationships,
    lookup_recording_relationships,
)

_DEFAULT_EXCLUSIONS = {
    "exclude_live": True,
    "exclude_covers": True,
    "exclude_remixes": True,
}

_CATEGORY_TERMS: dict[str, tuple[str, ...]] = {
    "live": ("live",),
    "remix": (
        "remix",
        "360 reality audio",
        "surround mix",
        "5.1 mix",
        "quadraphonic",
    ),
    "cover": ("cover", "karaoke", "tribute"),
    "alternate": ("rehearsal", "demo", "instrumental", "radio edit"),
}

_CATEGORY_PENALTIES = {
    "live": 35.0,
    "remix": 28.0,
    "cover": 35.0,
    "alternate": 28.0,
}


def normalize_exclusions(value: Any = None) -> dict[str, bool]:
    """Return the three supported exclusion flags with stable defaults."""
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    source = value if isinstance(value, Mapping) else {}
    return {
        key: bool(source.get(key, default))
        for key, default in _DEFAULT_EXCLUSIONS.items()
    }


def _contains_term(text: str, term: str) -> bool:
    pattern = rf"(?<!\w){re.escape(term)}(?!\w)"
    return re.search(pattern, text.casefold()) is not None


def musicbrainz_version_categories(match: Mapping[str, Any]) -> list[str]:
    """Detect version families from text plus MusicBrainz relationships."""
    secondary_types = match.get("release_group_secondary_types") or []
    text = " ".join(
        [
            str(match.get("recording_disambiguation", "")),
            str(match.get("release_title", "")),
            *[str(value) for value in secondary_types],
        ]
    )
    categories: list[str] = []
    for category, terms in _CATEGORY_TERMS.items():
        if any(_contains_term(text, term) for term in terms):
            categories.append(category)

    for value in match.get("relationship_version_categories") or []:
        category = str(value).strip().casefold()
        if category in _CATEGORY_TERMS and category not in categories:
            categories.append(category)
    return categories


def _base_confidence(match: Mapping[str, Any]) -> float:
    lexical_score = float(match.get("lexical_score", 0.0) or 0.0)
    release_quality_score = float(match.get("release_quality_score", 0.0) or 0.0)
    duration_score = match.get("duration_score")
    if duration_score is None:
        return lexical_score * 0.80 + release_quality_score * 0.20
    return (
        lexical_score * 0.60
        + float(duration_score or 0.0) * 0.30
        + release_quality_score * 0.10
    )


def apply_musicbrainz_policy(
    match: Mapping[str, Any],
    exclusions: Any = None,
) -> dict[str, Any]:
    """Recalculate version penalties and confidence for the selected user policy."""
    result = dict(match)
    active = normalize_exclusions(exclusions)
    categories = musicbrainz_version_categories(result)

    excluded_categories: list[str] = []
    if "live" in categories and active["exclude_live"]:
        excluded_categories.append("live")
    if "remix" in categories and active["exclude_remixes"]:
        excluded_categories.append("remix")
    if "cover" in categories and active["exclude_covers"]:
        excluded_categories.append("cover")
    if "alternate" in categories:
        excluded_categories.append("alternate")

    penalty = sum(_CATEGORY_PENALTIES[item] for item in excluded_categories)
    if str(result.get("release_status", "")).strip().casefold() == "bootleg":
        penalty += 20.0
    penalty = min(60.0, penalty)

    confidence = round(max(0.0, _base_confidence(result) - penalty), 1)
    lexical_score = float(result.get("lexical_score", 0.0) or 0.0)
    matched = (
        bool(result.get("recording_mbid"))
        and not excluded_categories
        and lexical_score >= MATCH_THRESHOLD
        and confidence >= MATCH_THRESHOLD
    )

    result.update(
        {
            "version_categories": categories,
            "policy_excluded_categories": excluded_categories,
            "active_exclusions": active,
            "version_penalty": round(penalty, 1),
            "confidence": confidence,
            "matched": matched,
        }
    )
    return result


def _rank(item: Mapping[str, Any]) -> tuple[float, float, float, int, float]:
    year = int(item.get("effective_release_year") or 9999)
    return (
        float(item.get("confidence", 0.0)),
        float(item.get("duration_score") or 0.0),
        float(item.get("release_quality_score", 0.0)),
        -year,
        float(item.get("lexical_score", 0.0)),
    )


class PolicyAwareMusicBrainzClient(MusicBrainzClient):
    """MusicBrainz client that ranks versions according to PlaylistMuse options."""

    async def _enrich_candidate(
        self,
        candidate: dict[str, Any],
        exclusions: Any,
    ) -> dict[str, Any]:
        recording_mbid = str(candidate.get("recording_mbid", "")).strip()
        if not recording_mbid:
            return candidate
        try:
            relationship_data = await lookup_recording_relationships(
                self._client,
                recording_mbid,
            )
        except Exception as error:
            return {
                **candidate,
                "relationship_lookup_complete": False,
                "relationship_lookup_error": type(error).__name__,
            }
        enriched = enrich_match_with_relationships(candidate, relationship_data)
        return apply_musicbrainz_policy(enriched, exclusions)

    async def search_track(
        self,
        title: str,
        artists: str,
        *,
        duration_ms: int | None = None,
        exclusions: Any = None,
    ) -> dict[str, Any] | None:
        query = build_recording_query(title, artists)
        response = await _rate_limited_get(
            self._client,
            params={"query": query, "fmt": "json", "limit": 25},
        )
        response.raise_for_status()
        payload = response.json()
        recordings = payload.get("recordings") if isinstance(payload, dict) else None
        if not isinstance(recordings, list):
            return None

        candidates = [
            apply_musicbrainz_policy(
                _candidate_payload(recording, title, artists, duration_ms),
                exclusions,
            )
            for recording in recordings
            if isinstance(recording, dict)
        ]
        if not candidates:
            return None

        exact_candidates = [
            item for item in candidates if float(item.get("lexical_score", 0.0)) >= 90.0
        ]
        pool = exact_candidates or candidates

        if duration_ms is not None:
            close_candidates = [
                item
                for item in pool
                if item.get("duration_delta_ms") is not None
                and int(item["duration_delta_ms"]) <= 45_000
            ]
            if close_candidates:
                pool = close_candidates

        ordered = sorted(pool, key=_rank, reverse=True)
        active = normalize_exclusions(exclusions)
        relationship_checks = 3 if any(active.values()) else 1
        enriched_candidates = [
            await self._enrich_candidate(candidate, exclusions)
            for candidate in ordered[:relationship_checks]
        ]

        policy_compatible = [
            item
            for item in enriched_candidates
            if not item.get("policy_excluded_categories")
        ]
        final_pool = policy_compatible or enriched_candidates or ordered
        return max(final_pool, key=_rank)
