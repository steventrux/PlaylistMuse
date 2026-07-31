from __future__ import annotations

from io import BytesIO

import httpx
import pytest
from PIL import Image

from backend import playlist_cover, youtube_playlist_service


def _image_bytes(color: tuple[int, int, int], image_format: str = "JPEG") -> bytes:
    output = BytesIO()
    Image.new("RGB", (80, 60), color).save(output, format=image_format)
    return output.getvalue()


class _ImageClient:
    def __init__(self, responses: dict[str, bytes]):
        self.responses = responses

    def get(self, url: str, headers: dict[str, str]):
        request = httpx.Request("GET", url)
        return httpx.Response(
            200,
            headers={"content-type": "image/jpeg"},
            content=self.responses[url],
            request=request,
        )


def test_thumbnail_urls_are_deduplicated_and_host_validated() -> None:
    values = [
        "https://lh3.googleusercontent.com/one",
        "https://i.ytimg.com/two",
        "https://lh3.googleusercontent.com/one",
        "https://yt3.ggpht.com/three",
        "https://evil-ytimg.com/four",
        "http://i.ytimg.com/insecure",
        "https://sub.ytimg.com/four",
    ]

    assert playlist_cover.normalize_thumbnail_urls(values) == [
        "https://lh3.googleusercontent.com/one",
        "https://i.ytimg.com/two",
        "https://yt3.ggpht.com/three",
        "https://sub.ytimg.com/four",
    ]


def test_build_playlist_cover_returns_square_jpeg() -> None:
    urls = [f"https://i.ytimg.com/{index}" for index in range(4)]
    colors = [
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        (255, 255, 0),
    ]
    client = _ImageClient(
        {url: _image_bytes(color) for url, color in zip(urls, colors, strict=True)}
    )

    encoded = playlist_cover.build_playlist_cover(client, urls)

    assert len(encoded) < playlist_cover.MAX_COVER_BYTES
    with Image.open(BytesIO(encoded)) as cover:
        assert cover.format == "JPEG"
        assert cover.size == (playlist_cover.COVER_SIZE, playlist_cover.COVER_SIZE)
        assert cover.getpixel((64, 64))[0] > 200
        assert cover.getpixel((448, 64))[1] > 200
        assert cover.getpixel((64, 448))[2] > 200


def test_upload_playlist_cover_uses_hero_multipart_and_refreshes_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cover = _image_bytes((20, 30, 40))
    monkeypatch.setattr(playlist_cover, "build_playlist_cover", lambda *args: cover)

    calls: list[tuple[dict[str, str], bytes, dict[str, str]]] = []
    tokens: list[bool] = []

    class Client:
        def post(self, url, params, content, headers):
            calls.append((params, content, headers))
            status = 401 if len(calls) == 1 else 200
            return httpx.Response(status, request=httpx.Request("POST", url))

    def access_token(force_refresh: bool) -> str:
        tokens.append(force_refresh)
        return "fresh" if force_refresh else "stale"

    playlist_cover.upload_playlist_cover(
        Client(),
        "playlist-id",
        ["https://i.ytimg.com/example"] * 4,
        access_token,
    )

    assert tokens == [False, True]
    assert len(calls) == 2
    params, content, headers = calls[-1]
    assert params == {"part": "snippet", "uploadType": "multipart"}
    assert b'"playlistId":"playlist-id"' in content
    assert b'"type":"hero"' in content
    assert cover in content
    assert headers["Authorization"] == "Bearer fresh"
    assert headers["Content-Type"].startswith("multipart/related; boundary=")


@pytest.mark.asyncio
async def test_playlist_survives_cover_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_publish(*args):
        return {
            "playlist_id": "playlist-id",
            "warning": "Existing warning.",
            "url": "https://music.youtube.com/playlist?list=playlist-id",
        }

    def fail_upload(*args):
        raise playlist_cover.PlaylistCoverError("rejected")

    monkeypatch.setattr(youtube_playlist_service, "publish_playlist", fake_publish)
    monkeypatch.setattr(youtube_playlist_service, "_upload_cover_sync", fail_upload)

    result = await youtube_playlist_service.create_youtube_playlist(
        "Title",
        "Description",
        "PRIVATE",
        ["video-id"],
        [f"https://i.ytimg.com/{index}" for index in range(4)],
    )

    assert result["playlist_id"] == "playlist-id"
    assert result["cover_uploaded"] is False
    assert result["warning"].startswith("Existing warning.")
    assert "mosaic cover" in result["warning"]


@pytest.mark.asyncio
async def test_playlist_reports_uploaded_cover(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_publish(*args):
        return {"playlist_id": "playlist-id", "warning": None}

    monkeypatch.setattr(youtube_playlist_service, "publish_playlist", fake_publish)
    monkeypatch.setattr(youtube_playlist_service, "_upload_cover_sync", lambda *args: None)

    result = await youtube_playlist_service.create_youtube_playlist(
        "Title",
        "Description",
        "PRIVATE",
        ["video-id"],
        [f"https://i.ytimg.com/{index}" for index in range(4)],
    )

    assert result["cover_uploaded"] is True
    assert result["warning"] is None
