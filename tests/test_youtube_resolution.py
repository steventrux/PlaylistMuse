from __future__ import annotations

import backend.youtube as youtube_module


DEFAULT_EXCLUSIONS = {
    "exclude_live": True,
    "exclude_covers": True,
    "exclude_remixes": True,
}


def _result(
    *,
    video_id: str,
    title: str,
    artist: str,
    album: str,
) -> dict:
    return {
        "videoId": video_id,
        "title": title,
        "artists": [{"name": artist}],
        "album": {"name": album},
        "duration": "4:00",
        "thumbnails": [],
    }


def test_resolver_rejects_live_album_metadata_and_uses_studio_version(monkeypatch) -> None:
    class FakeClient:
        def search(self, query, filter, limit):
            assert limit == 12
            return [
                _result(
                    video_id="live-version",
                    title="The Chain",
                    artist="Fleetwood Mac",
                    album="In Session: Fleetwood Mac (Live)",
                ),
                _result(
                    video_id="studio-version",
                    title="The Chain",
                    artist="Fleetwood Mac",
                    album="Rumours",
                ),
            ]

    monkeypatch.setattr(youtube_module, "_client", lambda: FakeClient())

    track = youtube_module._resolve_one(
        {
            "artist": "Fleetwood Mac",
            "title": "The Chain",
            "description": "Description.",
            "reason": "Reason.",
        },
        DEFAULT_EXCLUSIONS,
    )

    assert track is not None
    assert track["video_id"] == "studio-version"
    assert track["album"] == "Rumours"


def test_resolver_rejects_tribute_cover_even_when_title_matches(monkeypatch) -> None:
    class FakeClient:
        def search(self, query, filter, limit):
            return [
                _result(
                    video_id="tribute-cover",
                    title="Them Bones",
                    artist="Mad Alice",
                    album="A Tribute to Alice in Chains & Mad Season",
                ),
                _result(
                    video_id="original",
                    title="Them Bones",
                    artist="Alice in Chains",
                    album="Dirt",
                ),
            ]

    monkeypatch.setattr(youtube_module, "_client", lambda: FakeClient())

    track = youtube_module._resolve_one(
        {
            "artist": "Alice in Chains",
            "title": "Them Bones",
            "description": "Description.",
            "reason": "Reason.",
        },
        DEFAULT_EXCLUSIONS,
    )

    assert track is not None
    assert track["video_id"] == "original"
    assert track["artists"] == "Alice in Chains"


def test_resolver_rejects_same_title_from_wrong_artist(monkeypatch) -> None:
    class FakeClient:
        def search(self, query, filter, limit):
            return [
                _result(
                    video_id="wrong-artist",
                    title="Them Bones",
                    artist="Mad Alice",
                    album="Original Album",
                )
            ]

    monkeypatch.setattr(youtube_module, "_client", lambda: FakeClient())

    track = youtube_module._resolve_one(
        {
            "artist": "Alice in Chains",
            "title": "Them Bones",
            "description": "Description.",
            "reason": "Reason.",
        },
        DEFAULT_EXCLUSIONS,
    )

    assert track is None


def test_resolver_accepts_legitimate_artist_variant(monkeypatch) -> None:
    class FakeClient:
        def search(self, query, filter, limit):
            return [
                _result(
                    video_id="steppenwolf-version",
                    title="Born to Be Wild",
                    artist="Steppenwolf",
                    album="Steppenwolf",
                )
            ]

    monkeypatch.setattr(youtube_module, "_client", lambda: FakeClient())

    track = youtube_module._resolve_one(
        {
            "artist": "John Kay, Steppenwolf",
            "title": "Born to Be Wild",
            "description": "Description.",
            "reason": "Reason.",
        },
        DEFAULT_EXCLUSIONS,
    )

    assert track is not None
    assert track["video_id"] == "steppenwolf-version"


def test_live_version_is_allowed_when_filter_is_disabled(monkeypatch) -> None:
    class FakeClient:
        def search(self, query, filter, limit):
            return [
                _result(
                    video_id="live-version",
                    title="The Chain",
                    artist="Fleetwood Mac",
                    album="In Session: Fleetwood Mac (Live)",
                )
            ]

    monkeypatch.setattr(youtube_module, "_client", lambda: FakeClient())

    track = youtube_module._resolve_one(
        {
            "artist": "Fleetwood Mac",
            "title": "The Chain",
            "description": "Description.",
            "reason": "Reason.",
        },
        {
            "exclude_live": False,
            "exclude_covers": True,
            "exclude_remixes": True,
        },
    )

    assert track is not None
    assert track["video_id"] == "live-version"
