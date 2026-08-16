import asyncio

from backend import musicbrainz_artist


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_artist_origin_lookup_resolves_country_and_reuses_cache(monkeypatch):
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


def test_artist_origin_lookup_caches_successful_missing_country(monkeypatch):
    calls = 0

    async def fake_get(client, url, params):
        nonlocal calls
        calls += 1
        return FakeResponse({"id": "artist-mbid", "name": "Unknown origin"})

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
