import asyncio
import time

from backend import musicbrainz_artist


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_artist_origin_lookup_resolves_country_and_reuses_cache(tmp_path, monkeypatch):
    calls = 0

    async def fake_get(client, url, params):
        nonlocal calls
        calls += 1
        assert url.endswith("/artist/artist-mbid")
        assert params == {"fmt": "json"}
        return FakeResponse(
            {
                "id": "artist-mbid",
                "name": "Måneskin",
                "country": "IT",
                "area": {"name": "Rome"},
            }
        )

    cache_path = tmp_path / "musicbrainz_artist_cache.sqlite3"
    monkeypatch.setattr(musicbrainz_artist, "_cache_path", lambda: cache_path)
    musicbrainz_artist.clear_artist_origin_cache()
    monkeypatch.setattr(musicbrainz_artist, "rate_limited_get", fake_get)

    async def scenario():
        first = await musicbrainz_artist.lookup_artist_origin("ARTIST-MBID")
        second = await musicbrainz_artist.lookup_artist_origin("artist-mbid")
        return first, second

    first, second = asyncio.run(scenario())

    assert first is not None
    assert first.country == "IT"
    assert first.area == "Rome"
    assert second == first
    assert calls == 1
    assert cache_path.exists()


def test_artist_origin_lookup_caches_successful_missing_country(tmp_path, monkeypatch):
    calls = 0

    async def fake_get(client, url, params):
        nonlocal calls
        calls += 1
        return FakeResponse({"id": "artist-mbid", "name": "Unknown origin"})

    cache_path = tmp_path / "musicbrainz_artist_cache.sqlite3"
    monkeypatch.setattr(musicbrainz_artist, "_cache_path", lambda: cache_path)
    musicbrainz_artist.clear_artist_origin_cache()
    monkeypatch.setattr(musicbrainz_artist, "rate_limited_get", fake_get)

    async def scenario():
        first = await musicbrainz_artist.lookup_artist_origin("artist-mbid")
        second = await musicbrainz_artist.lookup_artist_origin("artist-mbid")
        return first, second

    first, second = asyncio.run(scenario())

    assert first is not None
    assert first.country is None
    assert second == first
    assert calls == 1
    assert cache_path.exists()


def test_cache_put_purges_expired_rows_after_interval(tmp_path, monkeypatch):
    cache_path = tmp_path / "musicbrainz_artist_cache.sqlite3"
    monkeypatch.setattr(musicbrainz_artist, "_cache_path", lambda: cache_path)
    monkeypatch.setattr(musicbrainz_artist, "_last_purge_at", 0.0)

    with musicbrainz_artist._connect() as connection:
        connection.execute(
            "INSERT INTO artist_origin_cache(artist_mbid, country, area, expires_at) "
            "VALUES (?, ?, ?, ?)",
            ("stale-mbid", "IT", "Rome", time.time() - 10),
        )

    musicbrainz_artist._cache_put(
        "fresh-mbid", musicbrainz_artist.ArtistOrigin(country="FR", area="Paris")
    )

    with musicbrainz_artist._connect() as connection:
        remaining = {
            row["artist_mbid"]
            for row in connection.execute(
                "SELECT artist_mbid FROM artist_origin_cache"
            ).fetchall()
        }
    assert "stale-mbid" not in remaining
