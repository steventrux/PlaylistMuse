from __future__ import annotations

from types import SimpleNamespace

from backend import creative_intent, generation_runtime
from backend.artist_quota_detection import artist_matches, quota_deficits
from backend.creative_intent import CreativeRejection
from backend.policy_enforcement import (
    _ACTIVE_POLICY,
    _POLICY_BASE_TRACKS,
    _REPLACEMENT_MODE,
)
from backend.selection_guard import guarded_select_resolved_tracks


def _track(artist: str, title: str) -> dict[str, str]:
    return {
        "artists": artist,
        "title": title,
        "album": "Album",
        "video_id": f"{artist}-{title}",
    }


def test_remembered_creative_rejection_cannot_reach_selection() -> None:
    creative_intent._CREATIVE_REJECTIONS.set(
        (
            CreativeRejection(
                "tiziano ferro",
                "xdono",
                0.70,
                "Does not sufficiently support the requested creative brief.",
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
        track_identity_key=lambda title, artists: (
            f"{str(artists).casefold()}::{title.casefold()}"
        )
    )
    selected = guarded_select_resolved_tracks(
        [
            _track(" TIZIANO FERRO ", "Xdono"),
            _track("Party Artist", "Party Track"),
        ],
        youtube=youtube,
        artist_matches=artist_matches,
        quota_deficits=quota_deficits,
    )

    assert [track["title"] for track in selected] == ["Party Track"]
    assert [
        track["title"]
        for track in generation_runtime._RESOLVED_SESSION_TRACKS.get()
    ] == ["Party Track"]
