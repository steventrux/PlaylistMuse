"""Provider-neutral contract for music catalogue integrations."""

from __future__ import annotations

from typing import Any, Protocol


class MusicCatalog(Protocol):
    """Minimal catalogue behaviour required by PlaylistMuse."""

    async def search_songs(
        self,
        query: str,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        """Search the catalogue for song entries."""
        ...

    async def resolve_candidates(
        self,
        candidates: list[dict[str, str]],
        exclusions: dict[str, bool],
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        """Resolve proposed tracks and return resolved and unresolved entries."""
        ...

    def track_identity_key(self, title: str, artists: str) -> str:
        """Return the catalogue's stable identity key for one song."""
        ...
