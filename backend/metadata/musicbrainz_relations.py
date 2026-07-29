"""Recording relationship enrichment for MusicBrainz shadow matching."""

from __future__ import annotations

from typing import Any, Mapping

from backend.metadata.musicbrainz import MUSICBRAINZ_API_URL, _rate_limited_get

_CATEGORY_ORDER = ("live", "remix", "cover", "alternate")


class _EndpointClient:
    """Route the shared rate limiter to a specific MusicBrainz lookup URL."""

    def __init__(self, client: Any, url: str) -> None:
        self._client = client
        self._url = url

    async def get(self, _ignored_url: str, *, params: dict[str, Any]) -> Any:
        return await self._client.get(self._url, params=params)


def _relation_attributes(relation: Mapping[str, Any]) -> set[str]:
    values: set[str] = set()
    for value in relation.get("attributes") or []:
        text = str(value).strip().casefold()
        if text:
            values.add(text)

    attribute_values = relation.get("attribute-values")
    if isinstance(attribute_values, Mapping):
        for key, value in attribute_values.items():
            for item in (key, value):
                text = str(item).strip().casefold()
                if text:
                    values.add(text)
    return values


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def parse_recording_relationships(payload: Any) -> dict[str, Any]:
    """Extract version categories and compact relationship evidence."""
    relations = payload.get("relations") if isinstance(payload, Mapping) else None
    if not isinstance(relations, list):
        relations = []

    categories: list[str] = []
    work_relationships: list[dict[str, Any]] = []
    recording_relationships: list[dict[str, Any]] = []

    for relation in relations:
        if not isinstance(relation, Mapping):
            continue
        target_type = str(relation.get("target-type", "")).strip().casefold()
        relation_type = str(relation.get("type", "")).strip()
        relation_type_folded = relation_type.casefold()
        direction = str(relation.get("direction", "")).strip().casefold()
        attributes = _relation_attributes(relation)

        if target_type == "work" and relation_type_folded == "performance":
            if "live" in attributes:
                _append_unique(categories, "live")
            if attributes.intersection({"cover", "karaoke"}):
                _append_unique(categories, "cover")
            if attributes.intersection({"demo", "instrumental", "a cappella", "acappella"}):
                _append_unique(categories, "alternate")

            work = relation.get("work")
            work_data = work if isinstance(work, Mapping) else {}
            work_relationships.append(
                {
                    "work_mbid": str(work_data.get("id", "")).strip() or None,
                    "work_title": str(work_data.get("title", "")).strip() or None,
                    "attributes": sorted(attributes),
                    "direction": direction or None,
                }
            )

        if target_type == "recording":
            # A backward relation means the current recording has derived versions;
            # only forward/unspecified relations describe the current recording itself.
            describes_current = direction != "backward"
            if describes_current and relation_type_folded in {"remix", "dj-mix"}:
                _append_unique(categories, "remix")
            if describes_current and relation_type_folded == "karaoke":
                _append_unique(categories, "cover")
            if describes_current and relation_type_folded in {
                "instrumental",
                "edit",
                "a cappella",
                "acappella",
            }:
                _append_unique(categories, "alternate")

            recording = relation.get("recording")
            recording_data = recording if isinstance(recording, Mapping) else {}
            recording_relationships.append(
                {
                    "type": relation_type or None,
                    "direction": direction or None,
                    "recording_mbid": str(recording_data.get("id", "")).strip() or None,
                    "recording_title": str(recording_data.get("title", "")).strip() or None,
                    "attributes": sorted(attributes),
                }
            )

    ordered_categories = [item for item in _CATEGORY_ORDER if item in categories]
    return {
        "relationship_version_categories": ordered_categories,
        "work_relationships": work_relationships,
        "recording_relationships": recording_relationships,
    }


async def lookup_recording_relationships(
    client: Any,
    recording_mbid: str,
) -> dict[str, Any]:
    """Look up work and recording relationships for one selected recording."""
    mbid = str(recording_mbid).strip()
    if not mbid:
        return parse_recording_relationships({})

    endpoint = _EndpointClient(client, f"{MUSICBRAINZ_API_URL}/{mbid}")
    response = await _rate_limited_get(
        endpoint,
        params={
            "fmt": "json",
            "inc": "work-rels+recording-rels",
        },
    )
    response.raise_for_status()
    return parse_recording_relationships(response.json())


def enrich_match_with_relationships(
    match: Mapping[str, Any],
    relationship_data: Mapping[str, Any],
) -> dict[str, Any]:
    """Copy a candidate and attach relationship-derived evidence."""
    result = dict(match)
    categories = list(result.get("relationship_version_categories") or [])
    for value in relationship_data.get("relationship_version_categories") or []:
        text = str(value).strip()
        if text and text not in categories:
            categories.append(text)

    result.update(
        {
            "relationship_lookup_complete": True,
            "relationship_version_categories": [
                item for item in _CATEGORY_ORDER if item in categories
            ],
            "work_relationships": list(relationship_data.get("work_relationships") or []),
            "recording_relationships": list(
                relationship_data.get("recording_relationships") or []
            ),
        }
    )
    return result
