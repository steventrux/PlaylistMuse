"""PlaylistMuse ASGI application composition root."""

from fastapi import Request

from backend.build_info import router as build_info_router
from backend.main import app
from backend.playlist_library import router as playlist_library_router
from backend.playlist_publication_sync import reconcile_deleted_youtube_playlists
from backend.playlist_refinement import router as playlist_refinement_router


@app.middleware("http")
async def refresh_library_publication_state(request: Request, call_next):
    """Refresh published/draft state before rendering the local playlist library."""
    if request.method == "GET" and request.url.path == "/api/library/playlists":
        await reconcile_deleted_youtube_playlists()
    return await call_next(request)


app.include_router(build_info_router, prefix="/api")
app.include_router(playlist_library_router, prefix="/api")
app.include_router(playlist_refinement_router, prefix="/api")

__all__ = ["app"]
