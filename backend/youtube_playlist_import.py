"""Fetch a YouTube Music playlist by URL for import as a local draft.

Read-only: this module never persists anything. The returned dict is shaped exactly
like a generation endpoint's result (see main.py's _generate()) so the frontend can
treat an import result identically to a freshly generated playlist -- same
sessionStorage handoff to playlist.html, same save-on-first-edit, same publish flow.

Uses the unauthenticated catalogue client (youtube_core.anonymous_client), not the
OAuth-connected one: ytmusicapi's get_playlist() works without an account for any
public or unlisted playlist -- exactly the "someone else's playlist" case this
feature targets. No YouTube Music account needs to be connected to import.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from backend.youtube_account import YouTubeAccountError
from backend.youtube_core import anonymous_client, serialize_song

MAX_IMPORTED_TRACKS = 300
# YouTube Music playlist IDs come in several prefixed shapes (PL..., OLAK5uy_...
# album-derived, RD.../RDCLAK5uy_... radio mixes, LM liked-music, ...) and new
# shapes keep appearing, so this only checks it looks like a real ID (length and
# character set) rather than maintaining an exhaustive prefix whitelist -- an
# actually-invalid ID still fails cleanly against the real API in
# fetch_playlist_for_import.
_PLAYLIST_ID_PATTERN = re.compile(r"^[\w-]{10,}$")


def parse_playlist_id(value: str) -> str:
    """Extract a bare YouTube Music playlist ID from a pasted URL or ID."""

    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme and parsed.netloc:
        playlist_id = (parse_qs(parsed.query).get("list") or [""])[0]
    else:
        playlist_id = text

    if playlist_id.startswith("VL"):
        playlist_id = playlist_id[2:]

    if not playlist_id or not _PLAYLIST_ID_PATTERN.match(playlist_id):
        raise YouTubeAccountError("Enter a valid YouTube Music playlist link.")
    return playlist_id


async def fetch_playlist_for_import(url_or_id: str) -> dict[str, Any]:
    playlist_id = parse_playlist_id(url_or_id)
    try:
        raw = await asyncio.to_thread(anonymous_client().get_playlist, playlist_id, limit=None)
    except YouTubeAccountError:
        raise
    except Exception as error:
        raise YouTubeAccountError(
            "This playlist is no longer available on YouTube Music."
        ) from error

    if not isinstance(raw, dict):
        raise YouTubeAccountError("This playlist is no longer available on YouTube Music.")

    raw_tracks = raw.get("tracks") or []
    tracks = [track for track in (serialize_song(item) for item in raw_tracks) if track]

    warning: str | None = None
    dropped = len(raw_tracks) - len(tracks)
    if len(tracks) > MAX_IMPORTED_TRACKS:
        warning = (
            f"Only the first {MAX_IMPORTED_TRACKS} of {len(tracks)} tracks were "
            "imported (PlaylistMuse's per-playlist limit)."
        )
        tracks = tracks[:MAX_IMPORTED_TRACKS]
    elif dropped:
        warning = f"{dropped} track(s) could not be imported (unavailable on YouTube Music)."

    if not tracks:
        raise YouTubeAccountError("This playlist has no importable tracks.")

    return {
        "name": str(raw.get("title", "")).strip()[:100] or "Imported playlist",
        "description": str(raw.get("description", "") or "").strip()[:2000],
        "prompt": "",
        "requested_count": len(tracks),
        "resolved_count": len(tracks),
        "tracks": tracks,
        "unresolved": [],
        "lastfm": None,
        "warning": warning,
        "youtube_import": {
            "source_playlist_id": playlist_id,
            "source_url": f"https://music.youtube.com/playlist?list={playlist_id}",
            "imported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
    }
