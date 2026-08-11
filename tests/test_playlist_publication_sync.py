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
    original_updated_at = "2025-01-15T10:30:00+00:00"
    with library._connect() as connection:
        connection.execute(
            "UPDATE playlists SET updated_at = ? WHERE id = ?",
            (original_updated_at, deleted["id"]),
        )

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
    assert deleted_record["updated_at"] == original_updated_at
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


def test_recent_reconciliation_uses_ttl_cache(
    tmp_path: Path,
    monkeypatch,
) -> None:
    library = PlaylistLibrary(tmp_path / "playlists.db")
    library.create(sample_playlist("Keep published", "PL_KEEP"))
    calls: list[list[str]] = []

    def fetch_existing(playlist_ids):
        calls.append(list(playlist_ids))
        return {"PL_KEEP"}

    clock = [100.0]
    monkeypatch.setattr(publication_sync, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        publication_sync,
        "_fetch_existing_youtube_playlist_ids",
        fetch_existing,
    )

    first = asyncio.run(publication_sync.reconcile_deleted_youtube_playlists(library))
    second = asyncio.run(publication_sync.reconcile_deleted_youtube_playlists(library))

    assert first == 0
    assert second == 0
    assert calls == [["PL_KEEP"]]

    clock[0] += publication_sync.RECONCILIATION_TTL_SECONDS + 1
    third = asyncio.run(publication_sync.reconcile_deleted_youtube_playlists(library))

    assert third == 0
    assert calls == [["PL_KEEP"], ["PL_KEEP"]]


def test_changed_published_ids_bypass_reconciliation_ttl(
    tmp_path: Path,
    monkeypatch,
) -> None:
    library = PlaylistLibrary(tmp_path / "playlists.db")
    library.create(sample_playlist("First", "PL_FIRST"))
    calls: list[set[str]] = []

    def fetch_existing(playlist_ids):
        ids = set(playlist_ids)
        calls.append(ids)
        return ids

    monkeypatch.setattr(publication_sync, "monotonic", lambda: 100.0)
    monkeypatch.setattr(
        publication_sync,
        "_fetch_existing_youtube_playlist_ids",
        fetch_existing,
    )

    asyncio.run(publication_sync.reconcile_deleted_youtube_playlists(library))
    library.create(sample_playlist("Second", "PL_SECOND"))
    asyncio.run(publication_sync.reconcile_deleted_youtube_playlists(library))

    assert calls == [
        {"PL_FIRST"},
        {"PL_FIRST", "PL_SECOND"},
    ]


def test_failed_verification_is_throttled_with_same_ttl(
    tmp_path: Path,
    monkeypatch,
) -> None:
    library = PlaylistLibrary(tmp_path / "playlists.db")
    library.create(sample_playlist("Keep published", "PL_KEEP"))
    calls = 0

    def fail_verification(playlist_ids):
        nonlocal calls
        calls += 1
        raise RuntimeError("temporary YouTube failure")

    monkeypatch.setattr(publication_sync, "monotonic", lambda: 100.0)
    monkeypatch.setattr(
        publication_sync,
        "_fetch_existing_youtube_playlist_ids",
        fail_verification,
    )

    asyncio.run(publication_sync.reconcile_deleted_youtube_playlists(library))
    asyncio.run(publication_sync.reconcile_deleted_youtube_playlists(library))

    assert calls == 1
