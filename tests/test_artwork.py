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


def test_batch_query_combines_album_artist_pairs() -> None:
    query = artwork._release_group_query(
        [
            ("AC/DC", "Back in Black"),
            ("Pink Floyd", "The Wall"),
        ]
    )

    assert 'releasegroup:"Back in Black"' in query
    assert 'artistname:"AC/DC"' in query
    assert 'releasegroup:"The Wall"' in query
    assert 'artistname:"Pink Floyd"' in query
    assert " OR " in query


def test_release_group_cover_uses_direct_front_500_endpoint() -> None:
    assert artwork._cover_art_url("release-group-mbid") == (
        "https://coverartarchive.org/release-group/release-group-mbid/front-500"
    )


def test_missing_album_returns_youtube_fallback_without_lookup(monkeypatch) -> None:
    called = False

    async def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("MusicBrainz must not be queried without an album")

    monkeypatch.setattr(artwork, "_search_release_groups", fail_if_called)

    result = asyncio.run(
        artwork.resolve_playlist_artwork(
            [
                {
                    "title": "Song",
                    "artists": "Artist",
                    "album": None,
                    "thumbnail_url": "https://example.test/youtube.jpg",
                }
            ]
        )
    )

    assert result == [
        {
            "source": "youtube",
            "artwork_url": "https://example.test/youtube.jpg",
            "release_group_mbid": None,
            "release_group_title": None,
        }
    ]
    assert called is False


def test_playlist_lookup_uses_one_search_and_caches_release_groups(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(artwork, "ARTWORK_DIR", tmp_path)
    monkeypatch.setattr(artwork, "ARTWORK_CACHE_PATH", tmp_path / "release-groups.json")

    lookup_calls = 0

    async def fake_search_release_groups(client, items):
        nonlocal lookup_calls
        del client
        lookup_calls += 1
        assert set(items) == {
            ("AC/DC", "Back in Black"),
            ("Pink Floyd", "The Wall"),
        }
        return {
            artwork._identity("AC/DC", "Back in Black"): {
                "id": "acdc-release-group",
                "title": "Back in Black",
            },
            artwork._identity("Pink Floyd", "The Wall"): {
                "id": "floyd-release-group",
                "title": "The Wall",
            },
        }

    monkeypatch.setattr(artwork, "_search_release_groups", fake_search_release_groups)

    tracks = [
        {
            "title": "Hells Bells",
            "artists": "AC/DC",
            "album": "Back in Black",
            "thumbnail_url": "https://example.test/hells-bells.jpg",
        },
        {
            "title": "You Shook Me All Night Long",
            "artists": "AC/DC",
            "album": "Back in Black",
            "thumbnail_url": "https://example.test/you-shook-me.jpg",
        },
        {
            "title": "Another Brick in the Wall",
            "artists": "Pink Floyd",
            "album": "The Wall",
            "thumbnail_url": "https://example.test/the-wall.jpg",
        },
    ]

    first = asyncio.run(artwork.resolve_playlist_artwork(tracks))
    second = asyncio.run(artwork.resolve_playlist_artwork(tracks))

    assert lookup_calls == 1
    assert first == second
    assert first[0]["artwork_url"] == (
        "https://coverartarchive.org/release-group/acdc-release-group/front-500"
    )
    assert first[1]["release_group_mbid"] == "acdc-release-group"
    assert first[2]["release_group_title"] == "The Wall"
    assert (tmp_path / "release-groups.json").is_file()
    assert not (tmp_path / "images").exists()


def test_public_artwork_api_is_batch_only_and_capped_at_four() -> None:
    schema = app.openapi()
    paths = set(schema["paths"])

    assert "/api/artwork/playlist" in paths
    assert "/api/artwork/track" not in paths
    assert "/api/artwork/images/{filename}" not in paths
    assert "/api/youtube/settings" in paths
    assert "/api/youtube/status" in paths
    assert "/api/youtube/connect/start" in paths
    assert "/api/youtube/connect/poll" in paths
    assert "/api/youtube/connection" in paths
    assert "/api/youtube/playlists" in paths

    request_schema = schema["components"]["schemas"]["PlaylistArtworkRequest"]
    assert request_schema["properties"]["tracks"]["maxItems"] == 4


def test_frontend_shows_youtube_mosaic_before_one_batch_upgrade() -> None:
    source = Path("frontend/playlist.js").read_text(encoding="utf-8")

    assert "const ARTWORK_ENDPOINT = '/api/artwork/playlist';" in source
    assert "renderPlaylistCover(fallbackUrls);" in source
    assert "Promise.all(tracks.map" in source
    assert "if (track.thumbnail_url) artwork.src = track.thumbnail_url;" in source
    assert "enrichTrackArtwork" not in source
    assert "album_artwork_url" not in source
    assert "/api/artwork/track" not in source
