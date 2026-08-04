import asyncio

from backend import constraint_relationships


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "release-groups": [
                {
                    "id": "6f93e803-6d68-3f2d-bc76-e3ec50445d60",
                    "title": "Load",
                    "score": 100,
                    "artist-credit": [
                        {
                            "name": "Metallica",
                            "artist": {"name": "Metallica"},
                        }
                    ],
                }
            ]
        }


class _Client:
    def __init__(self) -> None:
        self.params: dict[str, str] | None = None

    async def get(self, _url: str, *, params: dict[str, str]):
        self.params = params
        return _Response()


def test_album_artist_pair_is_verified_with_composite_query(monkeypatch):
    client = _Client()
    writes: list[tuple[str, str, dict]] = []

    async def fake_rate_limited_get(
        active_client: _Client,
        url: str,
        *,
        params: dict[str, str],
    ) -> _Response:
        return await active_client.get(url, params=params)

    monkeypatch.setattr(constraint_relationships, "_read_cache", lambda *_args: None)
    monkeypatch.setattr(
        constraint_relationships,
        "_write_cache",
        lambda album, artist, payload: writes.append((album, artist, payload)),
    )
    monkeypatch.setattr(
        constraint_relationships,
        "rate_limited_get",
        fake_rate_limited_get,
    )

    result = asyncio.run(
        constraint_relationships._verify_album_artist_pair(
            "Load",
            "Metallica",
            client,  # type: ignore[arg-type]
        )
    )

    assert result["matches"] is True
    assert result["album"] == "Load"
    assert client.params is not None
    assert 'releasegroup:"Load"' in client.params["query"]
    assert 'artist:"Metallica"' in client.params["query"]
    assert writes[0][0:2] == ("Load", "Metallica")


def test_pair_cache_key_distinguishes_artists():
    assert constraint_relationships._pair_key(
        "Load", "Metallica"
    ) != constraint_relationships._pair_key("Load", "Nirvana")
