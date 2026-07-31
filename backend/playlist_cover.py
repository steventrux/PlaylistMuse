"""Build and upload a safe square playlist cover."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from io import BytesIO
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

COVER_SIZE = 512
TILE_SIZE = COVER_SIZE // 2
MAX_SOURCE_BYTES = 5 * 1024 * 1024
MAX_SOURCE_PIXELS = 20_000_000
MAX_COVER_BYTES = 2 * 1024 * 1024
PLAYLIST_IMAGE_UPLOAD_URL = (
    "https://www.googleapis.com/upload/youtube/v3/playlistImages"
)
_ALLOWED_HOST_SUFFIXES = (
    "googleusercontent.com",
    "ggpht.com",
    "ytimg.com",
)


class PlaylistCoverError(RuntimeError):
    """Raised when a playlist mosaic cannot be built or uploaded safely."""


def _allowed_thumbnail_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False

    hostname = (parsed.hostname or "").casefold()
    return bool(
        parsed.scheme == "https"
        and hostname
        and any(
            hostname == suffix or hostname.endswith(f".{suffix}")
            for suffix in _ALLOWED_HOST_SUFFIXES
        )
    )


def normalize_thumbnail_urls(values: list[str]) -> list[str]:
    """Return up to four unique, trusted thumbnail URLs in source order."""

    normalized: list[str] = []
    seen: set[str] = set()

    for value in values:
        url = str(value or "").strip()
        if not url or url in seen or not _allowed_thumbnail_url(url):
            continue

        seen.add(url)
        normalized.append(url)
        if len(normalized) == 4:
            break

    return normalized


def _decode_tile(content: bytes) -> Image.Image:
    if not content or len(content) > MAX_SOURCE_BYTES:
        raise PlaylistCoverError("Invalid playlist thumbnail size.")

    try:
        with Image.open(BytesIO(content)) as source:
            width, height = source.size
            if width <= 0 or height <= 0 or width * height > MAX_SOURCE_PIXELS:
                raise PlaylistCoverError("Invalid playlist thumbnail dimensions.")

            source.load()
            return ImageOps.fit(
                source.convert("RGB"),
                (TILE_SIZE, TILE_SIZE),
                method=Image.Resampling.LANCZOS,
            )
    except (OSError, UnidentifiedImageError) as error:
        raise PlaylistCoverError("Invalid playlist thumbnail image.") from error


def build_playlist_cover(client: httpx.Client, thumbnail_urls: list[str]) -> bytes:
    """Download four trusted thumbnails and return a 512px JPEG mosaic."""

    urls = normalize_thumbnail_urls(thumbnail_urls)
    if len(urls) != 4:
        raise PlaylistCoverError("Four valid playlist thumbnails are required.")

    tiles: list[Image.Image] = []
    for url in urls:
        try:
            response = client.get(
                url,
                headers={"Accept": "image/jpeg,image/png,image/*;q=0.8"},
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise PlaylistCoverError("A playlist thumbnail could not be downloaded.") from error

        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
        if content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise PlaylistCoverError("Unsupported playlist thumbnail format.")
        tiles.append(_decode_tile(response.content))

    cover = Image.new("RGB", (COVER_SIZE, COVER_SIZE))
    positions = (
        (0, 0),
        (TILE_SIZE, 0),
        (0, TILE_SIZE),
        (TILE_SIZE, TILE_SIZE),
    )
    for tile, position in zip(tiles, positions, strict=True):
        cover.paste(tile, position)

    output = BytesIO()
    cover.save(output, format="JPEG", quality=88, optimize=True, progressive=True)
    encoded = output.getvalue()
    if not encoded or len(encoded) > MAX_COVER_BYTES:
        raise PlaylistCoverError("Generated playlist cover exceeds YouTube limits.")
    return encoded


def _multipart_body(playlist_id: str, image: bytes) -> tuple[bytes, str]:
    boundary = f"playlistmuse-{uuid.uuid4().hex}"
    metadata = json.dumps(
        {
            "snippet": {
                "playlistId": playlist_id,
                "type": "hero",
                "width": COVER_SIZE,
                "height": COVER_SIZE,
            }
        },
        separators=(",", ":"),
    ).encode("utf-8")
    marker = boundary.encode("ascii")
    body = b"\r\n".join(
        (
            b"--" + marker,
            b"Content-Type: application/json; charset=UTF-8",
            b"",
            metadata,
            b"--" + marker,
            b"Content-Type: image/jpeg",
            b"",
            image,
            b"--" + marker + b"--",
            b"",
        )
    )
    return body, boundary


def upload_playlist_cover(
    client: httpx.Client,
    playlist_id: str,
    thumbnail_urls: list[str],
    access_token: Callable[[bool], str],
) -> None:
    """Build and upload the playlist hero image using YouTube's media API."""

    image = build_playlist_cover(client, thumbnail_urls)
    body, boundary = _multipart_body(playlist_id, image)

    def send(force_refresh: bool) -> httpx.Response:
        return client.post(
            PLAYLIST_IMAGE_UPLOAD_URL,
            params={"part": "snippet", "uploadType": "multipart"},
            content=body,
            headers={
                "Authorization": f"Bearer {access_token(force_refresh)}",
                "Accept": "application/json",
                "Content-Type": f"multipart/related; boundary={boundary}",
            },
        )

    response = send(False)
    if response.status_code == 401:
        response = send(True)
    if response.is_error:
        raise PlaylistCoverError(
            f"YouTube rejected the playlist cover with HTTP {response.status_code}."
        )
