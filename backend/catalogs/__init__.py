"""Music catalogue abstractions and provider adapters."""

from backend.catalogs.base import MusicCatalog
from backend.catalogs.youtube_music import YouTubeMusicCatalog, youtube_music_catalog

__all__ = ["MusicCatalog", "YouTubeMusicCatalog", "youtube_music_catalog"]
