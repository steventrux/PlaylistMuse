from __future__ import annotations

import asyncio
from pathlib import Path

from backend import artwork
from backend.main import app


def test_release_group_candidate_requires_album_and_artist_match() -> None:
    exact = {
        "id": "release-group-mbid",
        "title": "Back in Black",
        "score": 100,
        "primary-type": "Album",
        "artist-credit": [{"name": "AC/DC"}],
    }
    wrong_artist = {
        **exact,
        "artist-credit": [{"name": "Different Artist"}],
    }

    assert artwork._candidate_score(exact, "Back in Black", "AC/DC") >= 80
    assert artwork._candidate_score(wrong_artist, "Back in Black", "AC/DC") == 0


def test_preferred_cover_uses_front_500_thumbnail() -> None:
    payload = {
        "images": [
            {
                "front": False,
                "approved": True,
                "image": "http://example.test/other.jpg",
                "thumbnails": {"500": "http://example.test/other-500.jpg"},
            },
            {
                "front": True,
                "approved": True,
                "image": "http://example.test/front.jpg",
                "thumbnails": {"500": "http://example.test/front-500.jpg"},
            },
        ]
    }

    assert artwork._preferred_cover_url(payload) == "https://example.test/front-500.jpg"


def test_missing_album_returns_youtube_fallback_without_lookup(monkeypatch) -> None:
    called = False

    async def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("MusicBrainz must not be queried without an album")

    monkeypatch.setattr(artwork, "_find_release_group", fail_if_called)

    result = asyncio.run(
        artwork.resolve_track_artwork(
            title="Song",
            artists="Artist",
            album=None,
            thumbnail_url="https://example.test/youtube.jpg",
        )
    )

    assert result == {
        "source": "youtube",
        "artwork_url": "https://example.test/youtube.jpg",
        "release_group_mbid": None,
        "release_group_title": None,
    }
    assert called is False


def test_successful_release_group_lookup_is_cached_per_album(
    monkeypatch,
    tmp_path: Path,
) -> None:
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    monkeypatch.setattr(artwork, "ARTWORK_DIR", tmp_path)
    monkeypatch.setattr(artwork, "ARTWORK_IMAGE_DIR", image_dir)
    monkeypatch.setattr(artwork, "ARTWORK_CACHE_PATH", tmp_path / "release-groups.json")

    lookup_calls = 0

    async def fake_find_release_group(client, album, artists):
        nonlocal lookup_calls
        del client
        lookup_calls += 1
        assert album == "Back in Black"
        assert artists == "AC/DC"
        return {"id": "release-group-mbid", "title": "Back in Black"}

    async def fake_cover_url(client, release_group_mbid):
        del client
        assert release_group_mbid == "release-group-mbid"
        return "https://example.test/front-500.jpg"

    async def fake_download(client, release_group_mbid, source_url):
        del client
        assert release_group_mbid == "release-group-mbid"
        assert source_url == "https://example.test/front-500.jpg"
        filename = f"{'a' * 64}.jpg"
        (image_dir / filename).write_bytes(b"image")
        return filename

    monkeypatch.setattr(artwork, "_find_release_group", fake_find_release_group)
    monkeypatch.setattr(artwork, "_release_group_cover_url", fake_cover_url)
    monkeypatch.setattr(artwork, "_download_cover", fake_download)

    request = {
        "title": "Hells Bells",
        "artists": "AC/DC",
        "album": "Back in Black",
        "thumbnail_url": "https://example.test/youtube.jpg",
    }
    first = asyncio.run(artwork.resolve_track_artwork(**request))
    second = asyncio.run(
        artwork.resolve_track_artwork(
            **{**request, "title": "You Shook Me All Night Long"}
        )
    )

    expected = {
        "source": "musicbrainz",
        "artwork_url": f"/api/artwork/images/{'a' * 64}.jpg",
        "release_group_mbid": "release-group-mbid",
        "release_group_title": "Back in Black",
    }
    assert first == expected
    assert second == expected
    assert lookup_calls == 1


def test_existing_youtube_api_paths_are_preserved() -> None:
    paths = set(app.openapi()["paths"])

    assert "/api/artwork/track" in paths
    assert "/api/artwork/images/{filename}" in paths
    assert "/api/youtube/settings" in paths
    assert "/api/youtube/status" in paths
    assert "/api/youtube/connect/start" in paths
    assert "/api/youtube/connect/poll" in paths
    assert "/api/youtube/connection" in paths
    assert "/api/youtube/playlists" in paths


def test_track_cards_prioritize_stable_youtube_artwork() -> None:
    source = Path("frontend/playlist.js").read_text(encoding="utf-8")

    assert "return track.thumbnail_url || track.album_artwork_url || '';" in source
    assert "updateTrackArtwork" not in source
    assert "const remaining = data.tracks" not in source
