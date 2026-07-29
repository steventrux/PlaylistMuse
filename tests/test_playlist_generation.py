"""Regression tests for the extracted playlist generation service."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.schemas import PlaylistOptions
from backend.services import playlist_generation as service


def _candidate(index: int) -> dict[str, str]:
    return {
        "artist": f"Artist {index}",
        "title": f"Song {index}",
        "description": f"Description {index}",
        "reason": f"Reason {index}",
    }


def _resolved(index: int) -> dict[str, Any]:
    return {
        "video_id": f"video-{index}",
        "title": f"Song {index}",
        "artists": f"Artist {index}",
        "description": f"Description {index}",
        "reason": f"Reason {index}",
    }


def test_generate_playlist_preserves_success_contract(monkeypatch) -> None:
    config = object()
    candidates = [_candidate(index) for index in range(1, 6)]
    tracks = [_resolved(index) for index in range(1, 6)]

    async def fake_draft(received_config: object, prompt: str, count: int):
        assert received_config is config
        assert prompt == "Classic rock"
        assert count == 5
        return {
            "title": "Regression Playlist",
            "description": "A stable playlist contract.",
            "tracks": candidates,
        }

    async def fake_resolve(received_candidates: list[dict], exclusions: dict[str, bool]):
        assert received_candidates == candidates
        assert exclusions == {
            "exclude_live": True,
            "exclude_covers": False,
            "exclude_remixes": True,
        }
        return tracks, []

    monkeypatch.setattr(service, "load_config", lambda: config)
    monkeypatch.setattr(service, "generate_playlist_draft", fake_draft)
    monkeypatch.setattr(service, "resolve_candidates", fake_resolve)

    result = asyncio.run(
        service.generate_playlist(
            "Classic rock",
            5,
            PlaylistOptions(exclude_covers=False),
        )
    )

    assert result == {
        "name": "Regression Playlist",
        "description": "A stable playlist contract.",
        "prompt": "Classic rock",
        "requested_count": 5,
        "resolved_count": 5,
        "tracks": tracks,
        "unresolved": [],
    }


def test_generate_playlist_replenishes_without_duplicates(monkeypatch) -> None:
    config = object()
    initial = [_candidate(index) for index in range(1, 4)]
    refill = [_candidate(1), _candidate(4), _candidate(5)]
    draft_calls = 0
    resolve_calls = 0

    async def fake_draft(received_config: object, prompt: str, count: int):
        nonlocal draft_calls
        assert received_config is config
        draft_calls += 1
        if draft_calls == 1:
            assert prompt == "Road trip rock"
            assert count == 5
            return {
                "title": "Open Road",
                "description": "Driving rock songs.",
                "tracks": initial,
            }
        assert "The playlist still needs 2 resolvable songs" in prompt
        assert count == 8
        return {
            "title": "Ignored refill title",
            "description": "Ignored refill description",
            "tracks": refill,
        }

    async def fake_resolve(received_candidates: list[dict], exclusions: dict[str, bool]):
        nonlocal resolve_calls
        assert exclusions == {
            "exclude_live": True,
            "exclude_covers": True,
            "exclude_remixes": True,
        }
        resolve_calls += 1
        if resolve_calls == 1:
            assert received_candidates == initial
            return [_resolved(index) for index in range(1, 4)], []
        assert received_candidates == [_candidate(4), _candidate(5)]
        return [_resolved(4), _resolved(5)], []

    monkeypatch.setattr(service, "load_config", lambda: config)
    monkeypatch.setattr(service, "generate_playlist_draft", fake_draft)
    monkeypatch.setattr(service, "resolve_candidates", fake_resolve)

    result = asyncio.run(
        service.generate_playlist("Road trip rock", 5, PlaylistOptions())
    )

    assert draft_calls == 2
    assert resolve_calls == 2
    assert [track["video_id"] for track in result["tracks"]] == [
        "video-1",
        "video-2",
        "video-3",
        "video-4",
        "video-5",
    ]
    assert result["name"] == "Open Road"
    assert result["description"] == "Driving rock songs."


def test_generate_playlist_preserves_insufficient_tracks_error(monkeypatch) -> None:
    config = object()
    only_candidate = [_candidate(1)]

    async def fake_draft(received_config: object, prompt: str, count: int):
        del prompt, count
        assert received_config is config
        return {
            "title": "Too Narrow",
            "description": "Not enough resolvable tracks.",
            "tracks": only_candidate,
        }

    async def fake_resolve(received_candidates: list[dict], exclusions: dict[str, bool]):
        del exclusions
        if received_candidates == only_candidate:
            return [_resolved(1)], []
        return [], received_candidates

    monkeypatch.setattr(service, "load_config", lambda: config)
    monkeypatch.setattr(service, "generate_playlist_draft", fake_draft)
    monkeypatch.setattr(service, "resolve_candidates", fake_resolve)

    with pytest.raises(
        ValueError,
        match=r"PlaylistMuse found only 1 of 5 distinct tracks",
    ):
        asyncio.run(service.generate_playlist("One-song universe", 5, PlaylistOptions()))
