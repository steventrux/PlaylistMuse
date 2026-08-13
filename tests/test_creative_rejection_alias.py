from __future__ import annotations

from types import SimpleNamespace

from backend import creative_intent, generation_runtime
from backend.artist_quota_detection import artist_matches, quota_deficits
from backend.creative_intent import CreativeRejection
from backend.policy_enforcement import _ACTIVE_POLICY, _POLICY_BASE_TRACKS, _REPLACEMENT_MODE
from backend.selection_guard import guarded_select_resolved_tracks


def test_requested_identity_blocks_rejected_track_after_catalogue_artist_expansion() -> None:
    creative_intent._CREATIVE_REJECTIONS.set(
        (
            CreativeRejection(
                "original artist",
                "same song",
                0.8,
                "Does not support the requested creative brief.",
            ),
        )
    )
    generation_runtime._ACTIVE_RESOLUTION_QUOTAS.set(())
    generation_runtime._ACTIVE_EXACT_ARTIST_QUOTAS.set(())
    generation_runtime._REQUESTED_SESSION_COUNT.set(2)
    generation_runtime._RESOLVED_SESSION_TRACKS.set(())
    _ACTIVE_POLICY.set(None)
    _POLICY_BASE_TRACKS.set(())
    _REPLACEMENT_MODE.set(False)

    youtube = SimpleNamespace(
        track_identity_key=lambda title, artists: f"{str(artists).casefold()}::{title.casefold()}"
    )
    expanded = {
        "artists": "Original Artist, Collaborator",
        "title": "Same Song",
        "requested_artist": "Original Artist",
        "requested_title": "Same Song",
        "album": "Album",
        "video_id": "expanded",
    }
    safe = {
        "artists": "Safe Artist",
        "title": "Safe Song",
        "requested_artist": "Safe Artist",
        "requested_title": "Safe Song",
        "album": "Album",
        "video_id": "safe",
    }

    selected = guarded_select_resolved_tracks(
        [expanded, safe],
        youtube=youtube,
        artist_matches=artist_matches,
        quota_deficits=quota_deficits,
    )

    assert [track["title"] for track in selected] == ["Safe Song"]
