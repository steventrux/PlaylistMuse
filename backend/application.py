"""PlaylistMuse ASGI application composition root."""

from fastapi import Request
from fastapi.responses import JSONResponse

from backend.build_info import router as build_info_router
from backend.diagnostics import diagnostics_middleware, router as diagnostics_router
from backend.main import app
from backend.playlist_library import (
    PlaylistNotFoundError,
    get_library,
    router as playlist_library_router,
)
from backend.playlist_publication_sync import reconcile_deleted_youtube_playlists
from backend.playlist_refinement import router as playlist_refinement_router
from backend.playlist_studio import router as playlist_studio_router

_LIBRARY_PLAYLIST_PREFIX = "/api/library/playlists/"
_PUBLISHED_READ_ONLY_DETAIL = (
    "Published playlists are read-only. Duplicate this playlist to make changes."
)


def _protected_library_playlist_id(request: Request) -> str | None:
    """Return the playlist ID for API writes that mutate playlist contents."""
    if not request.url.path.startswith(_LIBRARY_PLAYLIST_PREFIX):
        return None

    remainder = request.url.path[len(_LIBRARY_PLAYLIST_PREFIX) :].strip("/")
    parts = remainder.split("/") if remainder else []
    if request.method == "PUT" and len(parts) == 1:
        return parts[0]
    if request.method == "POST" and len(parts) == 3 and parts[1:] == ["tags", "suggest"]:
        return parts[0]
    return None


@app.middleware("http")
async def protect_published_playlist_writes(request: Request, call_next):
    """Keep published library records immutable through the public API."""
    playlist_id = _protected_library_playlist_id(request)
    if playlist_id:
        try:
            record = get_library().get(playlist_id)
        except PlaylistNotFoundError:
            pass
        else:
            if record.get("status") == "published":
                return JSONResponse(
                    status_code=409,
                    content={"detail": _PUBLISHED_READ_ONLY_DETAIL},
                )
    return await call_next(request)


@app.middleware("http")
async def refresh_library_publication_state(request: Request, call_next):
    """Refresh published/draft state before rendering the local playlist library."""
    if request.method == "GET" and request.url.path == "/api/library/playlists":
        await reconcile_deleted_youtube_playlists()
    return await call_next(request)


@app.middleware("http")
async def record_diagnostics(request: Request, call_next):
    """Record API activity and attach references to server-side failures."""
    return await diagnostics_middleware(request, call_next)


app.include_router(build_info_router, prefix="/api")
app.include_router(diagnostics_router, prefix="/api")
app.include_router(playlist_library_router, prefix="/api")
app.include_router(playlist_refinement_router, prefix="/api")
app.include_router(playlist_studio_router, prefix="/api")

__all__ = ["app"]
