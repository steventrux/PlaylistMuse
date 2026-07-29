"""Tests for the provider-neutral music catalogue boundary."""

from __future__ import annotations

import asyncio
from typing import Any

from backend import youtube
from backend.catalogs.youtube_music import YouTubeMusicCatalog
from backend.schemas import PlaylistOptions
from backend.services import playlist_generation as service


def test_youtube_catalog_delegates_search_without_changing_results(monkeypatch) -> None:
    expected = [{"video_id": "abc", "title": "Song", "artists": "Artist"}]

    async def fake_search(query: str, limit: int):
        assert query == "Artist Song"
        assert limit == 7
        return expected

    monkeypatch.setattr(youtube, "search_songs", fake_search)

    result = asyncio.run(YouTubeMusicCatalog().search_songs("Artist Song", 7))

    assert result is expected


def test_youtube_catalog_delegates_resolution_and_identity(monkeypatch) -> None:
    candidates = [{"artist": "Artist", "title": "Song"}]
    exclusions = {
        "exclude_live": True,
        "exclude_covers": True,
        "exclude_remixes": True,
    }
    resolved = [{"video_id": "abc", "title": "Song", "artists": "Artist"}]

    async def fake_resolve(received_candidates, received_exclusions):
        assert received_candidates == candidates
        assert received_exclusions == exclusions
        return resolved, []

    def fake_identity(title: str, artists: str) -> str:
        return f"{artists.lower()}::{title.lower()}"

    monkeypatch.setattr(youtube, "resolve_candidates", fake_resolve)
    monkeypatch.setattr(youtube, "track_identity_key", fake_identity)

    catalog = YouTubeMusicCatalog()
    result = asyncio.run(catalog.resolve_candidates(candidates, exclusions))

    assert result == (resolved, [])
    assert catalog.track_identity_key("Song", "Artist") == "artist::song"


def test_playlist_service_accepts_a_catalog_implementation() -> None:
    candidates = [
        {
            "artist": f"Artist {index}",
            "title": f"Song {index}",
            "description": "Description.",
            "reason": "Reason.",
        }
        for index in range(1, 6)
    ]

    class FakeCatalog:
        def __init__(self) -> None:
            self.resolve_calls = 0

        async def search_songs(
            self,
            query: str,
            limit: int = 8,
        ) -> list[dict[str, Any]]:
            del query, limit
            return []

        async def resolve_candidates(
            self,
            received_candidates: list[dict[str, str]],
            exclusions: dict[str, bool],
        ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
            assert received_candidates == candidates
            assert exclusions == {
                "exclude_live": True,
                "exclude_covers": True,
                "exclude_remixes": True,
            }
            self.resolve_calls += 1
            return (
                [
                    {
                        "video_id": f"video-{index}",
                        "title": candidate["title"],
                        "artists": candidate["artist"],
                        "description": candidate["description"],
                        "reason": candidate["reason"],
                    }
                    for index, candidate in enumerate(candidates, start=1)
                ],
                [],
            )

        def track_identity_key(self, title: str, artists: str) -> str:
            return f"{artists.casefold()}::{title.casefold()}"

    async def fake_draft(config: object, prompt: str, count: int):
        assert config is test_config
        assert prompt == "Catalogue boundary"
        assert count == 5
        return {
            "title": "Boundary Test",
            "description": "A catalogue-independent playlist.",
            "tracks": candidates,
        }

    test_config = object()
    catalog = FakeCatalog()
    result = asyncio.run(
        service.generate_playlist(
            "Catalogue boundary",
            5,
            PlaylistOptions(),
            catalog=catalog,
            load_config_fn=lambda: test_config,
            generate_playlist_draft_fn=fake_draft,
        )
    )

    assert catalog.resolve_calls == 1
    assert result["resolved_count"] == 5
    assert [track["video_id"] for track in result["tracks"]] == [
        "video-1",
        "video-2",
        "video-3",
        "video-4",
        "video-5",
    ]
