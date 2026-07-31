"""Build a safe square playlist cover from YouTube Music thumbnails."""

from __future__ import annotations

from io import BytesIO
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

COVER_SIZE = 512
TILE_SIZE = COVER_SIZE // 2
MAX_SOURCE_BYTES = 5 * 1024 * 1024
MAX_SOURCE_PIXELS = 20_000_000
MAX_COVER_BYTES = 2 * 1024 * 1024
_ALLOWED_HOST_SUFFIXES = (
    "googleusercontent.com",
    "ggpht.com",
    "ytimg.com",
)


class PlaylistCoverError(RuntimeError):
    """Raised when a safe playlist mosaic cannot be generated."""


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
