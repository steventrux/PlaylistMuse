from __future__ import annotations

import time

import pytest

from backend import cache_metrics
import backend.youtube as youtube_module
from backend.youtube import _write_youtube_cache as _real_write_youtube_cache


DEFAULT_EXCLUSIONS = {
    "exclude_live": True,
    "exclude_covers": True,
    "exclude_remixes": True,
}


@pytest.fixture
def isolate_youtube_resolution(monkeypatch):
    monkeypatch.setattr(youtube_module, "_read_youtube_cache_entry", lambda *args, **kwargs: (False, None, None))
    monkeypatch.setattr(youtube_module, "_write_youtube_cache", lambda *args, **kwargs: None)


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


def test_resolver_rejects_live_album_metadata_and_uses_studio_version(monkeypatch, isolate_youtube_resolution) -> None:
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

    monkeypatch.setattr(youtube_module, "_thread_client", lambda: FakeClient())

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


def test_resolver_rejects_tribute_cover_even_when_title_matches(monkeypatch, isolate_youtube_resolution) -> None:
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

    monkeypatch.setattr(youtube_module, "_thread_client", lambda: FakeClient())

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


def test_resolver_rejects_tribute_artist_named_after_the_style_it_imitates(
    monkeypatch,
    isolate_youtube_resolution,
) -> None:
    """Regression test: a tribute act's channel name can literally contain the real
    artist's name (e.g. "Done Again (In The Style of Bryan Adams)"), which used to score
    a perfect artist match via token_set_ratio and slip past the cover/tribute filter
    since it doesn't contain the words "cover", "tribute" or "karaoke"."""

    class FakeClient:
        def search(self, query, filter, limit):
            return [
                _result(
                    video_id="tribute-act",
                    title="Run To You",
                    artist="Done Again (In The Style of Bryan Adams)",
                    album="Run To You",
                ),
                _result(
                    video_id="original",
                    title="Run To You",
                    artist="Bryan Adams",
                    album="Reckless",
                ),
            ]

    monkeypatch.setattr(youtube_module, "_thread_client", lambda: FakeClient())

    track = youtube_module._resolve_one(
        {
            "artist": "Bryan Adams",
            "title": "Run To You",
            "description": "Description.",
            "reason": "Reason.",
        },
        DEFAULT_EXCLUSIONS,
    )

    assert track is not None
    assert track["video_id"] == "original"
    assert track["artists"] == "Bryan Adams"


def test_resolver_rejects_same_title_from_wrong_artist(monkeypatch, isolate_youtube_resolution) -> None:
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

    monkeypatch.setattr(youtube_module, "_thread_client", lambda: FakeClient())

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


def test_resolver_accepts_legitimate_artist_variant(monkeypatch, isolate_youtube_resolution) -> None:
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

    monkeypatch.setattr(youtube_module, "_thread_client", lambda: FakeClient())

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

    monkeypatch.setattr(youtube_module, "_thread_client", lambda: FakeClient())

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


def test_write_youtube_cache_purges_expired_rows_after_interval(tmp_path, monkeypatch):
    cache_path = tmp_path / "youtube_resolution_cache.sqlite3"
    monkeypatch.setattr(youtube_module._core, "_youtube_cache_last_purge_at", 0.0)

    with youtube_module._youtube_cache_connect(cache_path) as connection:
        connection.execute(
            "INSERT INTO youtube_resolution_cache(cache_key, payload, expires_at) "
            "VALUES (?, ?, ?)",
            ("stale-key", None, time.time() - 10),
        )

    candidate = {"title": "Fresh Track", "artist": "Fresh Artist"}
    _real_write_youtube_cache(
        candidate, DEFAULT_EXCLUSIONS, {"video_id": "abc"}, path=cache_path
    )

    with youtube_module._youtube_cache_connect(cache_path) as connection:
        remaining = {
            row["cache_key"]
            for row in connection.execute(
                "SELECT cache_key FROM youtube_resolution_cache"
            ).fetchall()
        }
    assert "stale-key" not in remaining


def test_read_youtube_cache_entry_records_hit_and_miss_metrics(tmp_path):
    cache_path = tmp_path / "youtube_resolution_cache.sqlite3"
    before = cache_metrics.snapshot().get(
        "YouTube resolution", {"hits": 0, "misses": 0}
    )

    candidate = {"title": "Never Cached", "artist": "Nobody"}
    hit, _track, _diagnostic = youtube_module._read_youtube_cache_entry(
        candidate, DEFAULT_EXCLUSIONS, path=cache_path
    )
    assert hit is False
    after_miss = cache_metrics.snapshot()["YouTube resolution"]
    assert after_miss["misses"] == before["misses"] + 1

    hit_candidate = {"title": "Cached Track", "artist": "Cached Artist"}
    _real_write_youtube_cache(
        hit_candidate, DEFAULT_EXCLUSIONS, {"video_id": "abc"}, path=cache_path
    )
    hit, _track, _diagnostic = youtube_module._read_youtube_cache_entry(
        hit_candidate, DEFAULT_EXCLUSIONS, path=cache_path
    )
    assert hit is True
    after_hit = cache_metrics.snapshot()["YouTube resolution"]
    assert after_hit["hits"] == before["hits"] + 1
