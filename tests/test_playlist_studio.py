from __future__ import annotations

import pytest

from backend.playlist_studio import (
    _assert_immutable_positions,
    _merge_scoped_tracks,
    _resolve_scope,
    _scoped_record,
)


def _track(index: int) -> dict[str, str]:
    return {
        "video_id": f"video-{index}",
        "title": f"Track {index}",
        "artists": f"Artist {index}",
    }


def _record(count: int = 5) -> dict:
    tracks = [_track(index) for index in range(1, count + 1)]
    return {
        "id": "test-playlist",
        "name": "Test",
        "description": "",
        "prompt": "A focused rock playlist",
        "track_count": count,
        "playlist": {
            "name": "Test",
            "description": "",
            "prompt": "A focused rock playlist",
            "tracks": tracks,
            "requested_count": count,
            "resolved_count": count,
        },
        "generation_request": {},
    }


def test_scope_defaults_to_all_unlocked_tracks() -> None:
    editable, locked = _resolve_scope(5, [], [2, 4])
    assert editable == [1, 3, 5]
    assert locked == [2, 4]


def test_lock_wins_over_explicit_target() -> None:
    editable, locked = _resolve_scope(5, [2, 3, 4], [3])
    assert editable == [2, 4]
    assert locked == [3]


def test_scope_rejects_empty_editable_selection() -> None:
    with pytest.raises(ValueError, match="Select at least one unlocked track"):
        _resolve_scope(3, [2], [2])


def test_scoped_record_contains_only_editable_tracks() -> None:
    scoped = _scoped_record(_record(), [2, 4])
    assert [track["video_id"] for track in scoped["playlist"]["tracks"]] == [
        "video-2",
        "video-4",
    ]
    assert scoped["track_count"] == 2
    assert "Artist 1 — Track 1" in scoped["playlist"]["prompt"]
    assert "Artist 3 — Track 3" in scoped["playlist"]["prompt"]


def test_merge_changes_only_target_positions() -> None:
    source = [_track(index) for index in range(1, 6)]
    replacements = [
        {"video_id": "new-2", "title": "New 2", "artists": "New Artist 2"},
        {"video_id": "new-4", "title": "New 4", "artists": "New Artist 4"},
    ]
    merged = _merge_scoped_tracks(source, replacements, [2, 4])
    assert [track["video_id"] for track in merged] == [
        "video-1",
        "new-2",
        "video-3",
        "new-4",
        "video-5",
    ]


def test_merge_rejects_duplicate_with_protected_track() -> None:
    source = [_track(index) for index in range(1, 4)]
    with pytest.raises(ValueError, match="duplicate"):
        _merge_scoped_tracks(source, [dict(source[0])], [2])


def test_immutable_position_validation_rejects_out_of_scope_change() -> None:
    source = [_track(index) for index in range(1, 4)]
    preview = [dict(track) for track in source]
    preview[0] = {"video_id": "changed", "title": "Changed", "artists": "Someone"}
    with pytest.raises(ValueError, match="outside the Playlist Studio editing scope"):
        _assert_immutable_positions(source, preview, [2])
