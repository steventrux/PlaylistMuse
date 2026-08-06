"""PlaylistMuse ASGI application composition root."""

from backend.main import app
from backend.playlist_library import router as playlist_library_router

app.include_router(playlist_library_router, prefix="/api")

__all__ = ["app"]
