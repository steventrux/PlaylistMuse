"""YouTube Music implementation of the provider-neutral catalogue contract."""

from __future__ import annotations

from typing import Any

from backend import youtube


class YouTubeMusicCatalog:
    """Resolve and search tracks exclusively through YouTube Music."""

    async def search_songs(
        self,
        query: str,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        return await youtube.search_songs(query, limit)

    async def resolve_candidates(
        self,
        candidates: list[dict[str, str]],
        exclusions: dict[str, bool],
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        return await youtube.resolve_candidates(candidates, exclusions)

    def track_identity_key(self, title: str, artists: str) -> str:
        return youtube.track_identity_key(title, artists)


youtube_music_catalog = YouTubeMusicCatalog()
