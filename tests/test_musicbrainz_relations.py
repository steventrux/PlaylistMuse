"""Tests for MusicBrainz work and recording relationship enrichment."""

from __future__ import annotations

import asyncio
from typing import Any

from backend.metadata import musicbrainz_policy, musicbrainz_relations
from backend.metadata.musicbrainz_policy import (
    PolicyAwareMusicBrainzClient,
    apply_musicbrainz_policy,
)


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


def _candidate(recording_mbid: str = "recording") -> dict[str, Any]:
    return {
        "recording_mbid": recording_mbid,
        "recording_disambiguation": "",
        "release_title": "Official release",
        "release_status": "Official",
        "release_group_secondary_types": [],
        "lexical_score": 100.0,
        "duration_score": 100.0,
        "duration_delta_ms": 0,
        "release_quality_score": 100.0,
        "effective_release_year": 2000,
    }


def test_relationship_parser_detects_cover_live_and_forward_remix() -> None:
    parsed = musicbrainz_relations.parse_recording_relationships(
        {
            "relations": [
                {
                    "target-type": "work",
                    "type": "performance",
                    "direction": "forward",
                    "attributes": ["cover", "live"],
                    "work": {"id": "work-1", "title": "Hurt"},
                },
                {
                    "target-type": "recording",
                    "type": "remix",
                    "direction": "forward",
                    "recording": {"id": "source", "title": "Source mix"},
                },
                {
                    "target-type": "recording",
                    "type": "remix",
                    "direction": "backward",
                    "recording": {"id": "derived", "title": "Derived remix"},
                },
            ]
        }
    )

    assert parsed["relationship_version_categories"] == ["live", "remix", "cover"]
    assert parsed["work_relationships"][0]["work_mbid"] == "work-1"
    assert len(parsed["recording_relationships"]) == 2


def test_relationship_parser_reads_attribute_values() -> None:
    parsed = musicbrainz_relations.parse_recording_relationships(
        {
            "relations": [
                {
                    "target-type": "work",
                    "type": "performance",
                    "attribute-values": {"cover-id": "cover"},
                    "work": {"id": "work-1", "title": "Song"},
                }
            ]
        }
    )

    assert parsed["relationship_version_categories"] == ["cover"]


def test_relationship_only_cover_obeys_user_option() -> None:
    match = {
        **_candidate(),
        "relationship_version_categories": ["cover"],
    }

    excluded = apply_musicbrainz_policy(
        match,
        {"exclude_live": False, "exclude_covers": True, "exclude_remixes": False},
    )
    allowed = apply_musicbrainz_policy(
        match,
        {"exclude_live": False, "exclude_covers": False, "exclude_remixes": False},
    )

    assert excluded["version_categories"] == ["cover"]
    assert excluded["policy_excluded_categories"] == ["cover"]
    assert excluded["matched"] is False
    assert allowed["policy_excluded_categories"] == []
    assert allowed["matched"] is True


def test_relationship_lookup_uses_recording_endpoint_and_includes(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_get(client: object, *, params: dict[str, Any]) -> FakeResponse:
        captured["url"] = getattr(client, "_url")
        captured["params"] = params
        return FakeResponse({"relations": []})

    monkeypatch.setattr(musicbrainz_relations, "_rate_limited_get", fake_get)
    result = asyncio.run(
        musicbrainz_relations.lookup_recording_relationships(object(), "recording-1")
    )

    assert captured["url"].endswith("/recording-1")
    assert captured["params"] == {
        "fmt": "json",
        "inc": "work-rels+recording-rels",
    }
    assert result["relationship_version_categories"] == []


def test_policy_client_skips_relation_only_cover_when_excluded(monkeypatch) -> None:
    search_payload = {
        "recordings": [
            {
                "id": "cover-recording",
                "score": "100",
                "title": "Hurt",
                "length": 217000,
                "first-release-date": "2002",
                "artist-credit": [
                    {"artist": {"id": "cash", "name": "Johnny Cash"}}
                ],
                "releases": [
                    {
                        "id": "cover-release",
                        "title": "American IV",
                        "status": "Official",
                        "date": "2002",
                        "release-group": {
                            "id": "cover-group",
                            "primary-type": "Album",
                        },
                    }
                ],
            },
            {
                "id": "plain-recording",
                "score": "100",
                "title": "Hurt",
                "length": 218000,
                "first-release-date": "2003",
                "artist-credit": [
                    {"artist": {"id": "cash", "name": "Johnny Cash"}}
                ],
                "releases": [
                    {
                        "id": "plain-release",
                        "title": "Official release",
                        "status": "Official",
                        "date": "2003",
                        "release-group": {
                            "id": "plain-group",
                            "primary-type": "Album",
                        },
                    }
                ],
            },
        ]
    }

    async def fake_search_get(client: object, *, params: dict[str, Any]) -> FakeResponse:
        del client, params
        return FakeResponse(search_payload)

    async def fake_relationship_lookup(client: object, recording_mbid: str) -> dict[str, Any]:
        del client
        return {
            "relationship_version_categories": (
                ["cover"] if recording_mbid == "cover-recording" else []
            ),
            "work_relationships": [],
            "recording_relationships": [],
        }

    monkeypatch.setattr(musicbrainz_policy, "_rate_limited_get", fake_search_get)
    monkeypatch.setattr(
        musicbrainz_policy,
        "lookup_recording_relationships",
        fake_relationship_lookup,
    )

    client = PolicyAwareMusicBrainzClient(client=object())
    excluded = asyncio.run(
        client.search_track(
            "Hurt",
            "Johnny Cash",
            duration_ms=217000,
            exclusions={
                "exclude_live": False,
                "exclude_covers": True,
                "exclude_remixes": False,
            },
        )
    )
    allowed = asyncio.run(
        client.search_track(
            "Hurt",
            "Johnny Cash",
            duration_ms=217000,
            exclusions={
                "exclude_live": False,
                "exclude_covers": False,
                "exclude_remixes": False,
            },
        )
    )

    assert excluded is not None
    assert excluded["recording_mbid"] == "plain-recording"
    assert excluded["policy_excluded_categories"] == []
    assert allowed is not None
    assert allowed["recording_mbid"] == "cover-recording"
    assert allowed["version_categories"] == ["cover"]
