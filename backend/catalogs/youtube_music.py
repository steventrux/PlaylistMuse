"""YouTube Music implementation of the provider-neutral catalogue contract."""

from __future__ import annotations

from typing import Any

from backend import youtube
from backend.services.musicbrainz_filter import filter_musicbrainz_tracks


class YouTubeMusicCatalog:
    """Resolve through YouTube Music, then optionally validate version exclusions."""

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
        resolved, unresolved = await youtube.resolve_candidates(candidates, exclusions)
        accepted, rejected = await filter_musicbrainz_tracks(resolved, exclusions)
        unresolved.extend(
            {
                "artist": str(track.get("artists", "")),
                "title": str(track.get("title", "")),
                "description": str(track.get("description", "")),
                "reason": str(track.get("reason", "")),
            }
            for track in rejected
        )
        return accepted, unresolved

    def track_identity_key(self, title: str, artists: str) -> str:
        return youtube.track_identity_key(title, artists)


youtube_music_catalog = YouTubeMusicCatalog()
