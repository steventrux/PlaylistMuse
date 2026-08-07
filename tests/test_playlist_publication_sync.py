import asyncio
from pathlib import Path

import backend.playlist_publication_sync as publication_sync
from backend.playlist_library import PlaylistLibrary


def sample_playlist(name: str, playlist_id: str) -> dict:
    return {
        "name": name,
        "description": "Published playlist",
        "prompt": "A test playlist",
        "tracks": [
            {
                "video_id": "abc123",
                "title": "Track one",
                "artists": "Artist one",
            }
        ],
        "youtube_playlist": {
            "playlist_id": playlist_id,
            "url": f"https://music.youtube.com/playlist?list={playlist_id}",
        },
    }


def test_deleted_youtube_playlist_is_demoted_to_draft(
    tmp_path: Path,
    monkeypatch,
) -> None:
    library = PlaylistLibrary(tmp_path / "playlists.db")
    deleted = library.create(sample_playlist("Deleted", "PL_DELETED"))
    existing = library.create(sample_playlist("Existing", "PL_EXISTING"))

    monkeypatch.setattr(
        publication_sync,
        "_fetch_existing_youtube_playlist_ids",
        lambda playlist_ids: {"PL_EXISTING"},
    )

    changed = asyncio.run(publication_sync.reconcile_deleted_youtube_playlists(library))

    assert changed == 1

    deleted_record = library.get(deleted["id"])
    assert deleted_record["status"] == "draft"
    assert deleted_record["youtube_playlist_id"] is None
    assert deleted_record["youtube_playlist_url"] is None
    assert "youtube_playlist" not in deleted_record["playlist"]

    existing_record = library.get(existing["id"])
    assert existing_record["status"] == "published"
    assert existing_record["youtube_playlist_id"] == "PL_EXISTING"


def test_verification_failure_keeps_published_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    library = PlaylistLibrary(tmp_path / "playlists.db")
    published = library.create(sample_playlist("Keep published", "PL_KEEP"))

    def fail_verification(playlist_ids):
        raise RuntimeError("temporary YouTube failure")

    monkeypatch.setattr(
        publication_sync,
        "_fetch_existing_youtube_playlist_ids",
        fail_verification,
    )

    changed = asyncio.run(publication_sync.reconcile_deleted_youtube_playlists(library))

    assert changed == 0
    record = library.get(published["id"])
    assert record["status"] == "published"
    assert record["youtube_playlist_id"] == "PL_KEEP"
    assert record["youtube_playlist_url"].endswith("PL_KEEP")
