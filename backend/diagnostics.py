"""Privacy-conscious diagnostics, rotating logs and support endpoints."""

from __future__ import annotations

import io
import json
import logging
import os
import platform
import re
import secrets
import sqlite3
import time
import traceback
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from backend import cache_metrics
from backend.build_info import current_build_info
from backend.config import DATA_DIR, load_config
from backend.generation_counter import generations_by_month, total_generations
from backend.lastfm_settings import LASTFM_SETTINGS_PATH, lastfm_settings_response
from backend.playlist_library import DATABASE_PATH, SCHEMA_VERSION
from backend.storage import read_json_object
from backend.youtube_account import (
    YOUTUBE_SETTINGS_PATH,
    YOUTUBE_TOKEN_PATH,
    youtube_settings_response,
)

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])

LOG_DIR = DATA_DIR / "logs"
LOG_PATH = LOG_DIR / "playlistmuse.log"
LOG_MAX_BYTES = 1_048_576
LOG_BACKUP_COUNT = 3
LOGGER_NAME = "playlistmuse"
ERROR_REFERENCE_HEADER = "x-playlistmuse-error-reference"
MIN_USAGE_DAYS_FOR_ESTIMATE = 3

# (display name, on-disk path, TTL in days for the cache's normal/positive entries --
# used only to project a steady-state size estimate from real usage, not for eviction).
CACHE_FILES: tuple[tuple[str, Path, int], ...] = (
    ("Metadata validation", DATA_DIR / "metadata_cache.sqlite3", 90),
    ("YouTube resolution", DATA_DIR / "youtube_resolution_cache.sqlite3", 30),
    ("Constraint interpretation", DATA_DIR / "constraint_interpretation_cache.sqlite3", 30),
    ("Constraint relationships", DATA_DIR / "constraint_relationship_cache.sqlite3", 180),
    ("Entity resolution", DATA_DIR / "entity_resolution_cache.sqlite3", 180),
    ("MusicBrainz artist origin", DATA_DIR / "musicbrainz_artist_cache.sqlite3", 90),
)

_SENSITIVE_KEY_RE = re.compile(
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|cookie|"
    r"client[_-]?secret|password|secret|credential)",
    re.IGNORECASE,
)
_TEXT_SECRET_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[^\s,;]+"),
    re.compile(r"(?i)\b(sk-(?:or-v1-)?[A-Za-z0-9_-]{12,})\b"),
    re.compile(r"\b(AIza[A-Za-z0-9_-]{20,})\b"),
    re.compile(
        r"(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|"
        r"cookie|client[_-]?secret|password|secret)\s*[:=]\s*)([^\s,;]+)"
    ),
    re.compile(
        r"(?i)([?&](?:api[_-]?key|key|token|secret|password)=)([^&#\s]+)"
    ),
)


class FrontendErrorReport(BaseModel):
    message: str = Field(min_length=1, max_length=1200)
    source: str = Field(default="", max_length=500)
    path: str = Field(default="", max_length=500)
    line: int | None = Field(default=None, ge=0)
    column: int | None = Field(default=None, ge=0)
    stack: str = Field(default="", max_length=6000)
    kind: str = Field(default="javascript", max_length=80)


class _SanitizingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = sanitize_text(record.getMessage())
        record.args = ()
        return True


def sanitize_text(text: str, *, secret_values: tuple[str, ...] = ()) -> str:
    """Redact common credentials and known local secret values from arbitrary text."""
    sanitized = str(text)
    for secret in secret_values:
        value = str(secret or "").strip()
        if len(value) >= 6:
            sanitized = sanitized.replace(value, "[REDACTED]")
    for pattern in _TEXT_SECRET_PATTERNS:
        if pattern.groups >= 2:
            sanitized = pattern.sub(r"\1[REDACTED]", sanitized)
        else:
            sanitized = pattern.sub("[REDACTED]", sanitized)
    return sanitized


def sanitize_data(value: Any, *, secret_values: tuple[str, ...] = ()) -> Any:
    """Recursively redact sensitive fields before diagnostic data leaves the process."""
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _SENSITIVE_KEY_RE.search(key_text):
                sanitized[key_text] = item if isinstance(item, bool) else "[REDACTED]"
            else:
                sanitized[key_text] = sanitize_data(item, secret_values=secret_values)
        return sanitized
    if isinstance(value, list):
        return [sanitize_data(item, secret_values=secret_values) for item in value]
    if isinstance(value, tuple):
        return [sanitize_data(item, secret_values=secret_values) for item in value]
    if isinstance(value, str):
        return sanitize_text(value, secret_values=secret_values)
    return value


def _known_secret_values() -> tuple[str, ...]:
    values: list[str] = []
    try:
        config = load_config()
        values.extend(config.provider_api_keys.values())
        if config.api_key:
            values.append(config.api_key)
    except Exception:
        pass

    for path in (LASTFM_SETTINGS_PATH, YOUTUBE_SETTINGS_PATH, YOUTUBE_TOKEN_PATH):
        try:
            payload = read_json_object(path)
        except Exception:
            continue
        for key, item in payload.items():
            if _SENSITIVE_KEY_RE.search(str(key)) and isinstance(item, str):
                values.append(item)

    for key, item in os.environ.items():
        if _SENSITIVE_KEY_RE.search(key):
            values.append(item)

    return tuple(dict.fromkeys(value.strip() for value in values if value and value.strip()))


def configure_diagnostics_logging() -> logging.Logger:
    """Configure the rotating PlaylistMuse log file and console output, without disturbing Uvicorn logging.

    Every backend module that wants its logs to go anywhere must log through this "playlistmuse"
    namespace (or a dotted child of it, e.g. "playlistmuse.performance") -- a logger created via
    logging.getLogger(__name__) resolves to "backend.<module>", a sibling namespace with no handler
    of its own, so its records are silently dropped. The console handler exists specifically so
    `docker logs` shows live activity; both handlers share the same secret-redacting filter so
    neither destination can leak credentials.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if any(getattr(handler, "_playlistmuse_diagnostics", False) for handler in logger.handlers):
        return logger

    formatter = logging.Formatter(
        "%(asctime)sZ %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime

    console_handler = logging.StreamHandler()
    console_handler._playlistmuse_diagnostics = True  # type: ignore[attr-defined]
    console_handler.addFilter(_SanitizingFilter())
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_PATH,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        return logger

    file_handler._playlistmuse_diagnostics = True  # type: ignore[attr-defined]
    file_handler.addFilter(_SanitizingFilter())
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


LOGGER = configure_diagnostics_logging()


def new_error_reference() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return f"PM-{stamp}-{secrets.token_hex(3).upper()}"


def _log_exception(error: Exception, *, reference: str, method: str, path: str) -> None:
    secret_values = _known_secret_values()
    traceback_text = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )
    safe_traceback = sanitize_text(traceback_text, secret_values=secret_values)
    LOGGER.error(
        "error_reference=%s method=%s path=%s exception_type=%s traceback=%s",
        reference,
        method,
        path,
        type(error).__name__,
        safe_traceback,
    )


def _error_detail(detail: str, reference: str) -> str:
    clean = detail.strip() or "PlaylistMuse could not complete the request."
    if "Error reference:" in clean:
        return clean
    return f"{clean} Error reference: {reference}"


async def _response_body(response: Response) -> bytes:
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:  # type: ignore[attr-defined]
        chunks.append(chunk.encode("utf-8") if isinstance(chunk, str) else chunk)
    return b"".join(chunks)


async def diagnostics_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Log API requests and attach a stable reference to server-side failures."""
    started = time.perf_counter()
    path = request.url.path
    method = request.method

    try:
        response = await call_next(request)
    except Exception as error:
        reference = new_error_reference()
        _log_exception(error, reference=reference, method=method, path=path)
        return JSONResponse(
            status_code=500,
            content={
                "detail": _error_detail(
                    "PlaylistMuse encountered an unexpected server error.", reference
                )
            },
            headers={ERROR_REFERENCE_HEADER: reference},
        )

    elapsed_ms = (time.perf_counter() - started) * 1000
    if path.startswith("/api/"):
        LOGGER.info(
            "request method=%s path=%s status=%s duration_ms=%.1f",
            method,
            path,
            response.status_code,
            elapsed_ms,
        )

    if response.status_code < 500:
        return response

    reference = response.headers.get(ERROR_REFERENCE_HEADER) or new_error_reference()
    LOGGER.error(
        "error_reference=%s method=%s path=%s status=%s",
        reference,
        method,
        path,
        response.status_code,
    )
    response.headers[ERROR_REFERENCE_HEADER] = reference

    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type.lower() or not hasattr(response, "body_iterator"):
        return response

    body = await _response_body(response)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return Response(
            content=body,
            status_code=response.status_code,
            headers=dict(response.headers),
            background=response.background,
        )

    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str):
            payload["detail"] = _error_detail(detail, reference)
        payload["error_reference"] = reference

    headers = dict(response.headers)
    headers.pop("content-length", None)
    headers[ERROR_REFERENCE_HEADER] = reference
    return Response(
        content=json.dumps(payload),
        status_code=response.status_code,
        headers=headers,
        background=response.background,
    )


def _database_metadata() -> dict[str, Any]:
    if not DATABASE_PATH.exists():
        return {
            "present": False,
            "schema_version": SCHEMA_VERSION,
            "size_bytes": 0,
            "playlist_count": 0,
            "track_count": 0,
        }
    actual_schema = None
    playlist_count = 0
    track_count = 0
    try:
        with sqlite3.connect(DATABASE_PATH) as connection:
            actual_schema = int(connection.execute("PRAGMA user_version").fetchone()[0])
            row = connection.execute(
                "SELECT COUNT(*) AS playlists, COALESCE(SUM(track_count), 0) AS tracks "
                "FROM playlists"
            ).fetchone()
            playlist_count, track_count = int(row[0]), int(row[1])
    except (OSError, sqlite3.Error, TypeError, ValueError):
        pass
    try:
        size = DATABASE_PATH.stat().st_size
    except OSError:
        size = 0
    return {
        "present": True,
        "schema_version": actual_schema,
        "expected_schema_version": SCHEMA_VERSION,
        "size_bytes": size,
        "playlist_count": playlist_count,
        "track_count": track_count,
    }


def _log_metadata() -> dict[str, Any]:
    total = 0
    for index in range(LOG_BACKUP_COUNT + 1):
        path = LOG_PATH if index == 0 else Path(f"{LOG_PATH}.{index}")
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return {"size_bytes": total}


def _usage_days_active() -> int:
    """Days since this installation's earliest recorded generation month.

    Approximates "how long has real usage been accumulating" from data already
    tracked locally (see generation_counter.py) -- used only to project a
    steady-state cache size from this installation's own usage, not a generic guess.
    """
    months = generations_by_month()
    if not months:
        return 0
    earliest = min(months)
    try:
        start = datetime.strptime(earliest, "%Y-%m").replace(tzinfo=UTC)
    except ValueError:
        return 0
    return max(0, (datetime.now(UTC) - start).days)


def _estimated_steady_state_bytes(size_bytes: int, ttl_days: int, days_active: int) -> int:
    """Project the size a cache will stabilize at once the hourly purge has been
    running for a full TTL window, extrapolating this installation's own current
    growth rate (size accumulated so far / days it's had to accumulate)."""
    if days_active <= 0 or days_active >= ttl_days:
        return size_bytes
    return round(size_bytes * (ttl_days / days_active))


def _cache_metrics_for(name: str) -> dict[str, Any]:
    counts = cache_metrics.snapshot().get(name, {"hits": 0, "misses": 0})
    hits, misses = counts["hits"], counts["misses"]
    total = hits + misses
    return {
        "hits": hits,
        "misses": misses,
        "hit_rate": round(hits / total, 3) if total else None,
    }


def _cache_metadata() -> dict[str, Any]:
    days_active = _usage_days_active()
    caches: list[dict[str, Any]] = []
    total = 0
    estimated_total = 0
    for name, path, ttl_days in CACHE_FILES:
        try:
            size = path.stat().st_size
            present = True
        except OSError:
            size = 0
            present = False
        estimate = _estimated_steady_state_bytes(size, ttl_days, days_active)
        total += size
        estimated_total += estimate
        caches.append(
            {
                "name": name,
                "size_bytes": size,
                "present": present,
                "estimated_steady_state_bytes": estimate,
                **_cache_metrics_for(name),
            }
        )
    return {
        "caches": caches,
        "total_bytes": total,
        "estimated_steady_state_total_bytes": estimated_total,
    }


def _data_dir_total_bytes() -> int:
    try:
        return sum(
            path.stat().st_size for path in DATA_DIR.rglob("*") if path.is_file()
        )
    except OSError:
        return 0


def _storage_payload() -> dict[str, Any]:
    cache_info = _cache_metadata()
    days_active = _usage_days_active()
    return {
        "data_dir_total_bytes": _data_dir_total_bytes(),
        "database": _database_metadata(),
        "logs": _log_metadata(),
        "caches": cache_info["caches"],
        "caches_total_bytes": cache_info["total_bytes"],
        "caches_estimated_steady_state_total_bytes": cache_info[
            "estimated_steady_state_total_bytes"
        ],
        "usage": {
            "total_generations": total_generations(),
            "days_active": days_active,
            "estimate_reliable": days_active >= MIN_USAGE_DAYS_FOR_ESTIMATE,
        },
    }


def _diagnostic_payload() -> dict[str, Any]:
    build = asdict(current_build_info())
    config = load_config()
    lastfm = lastfm_settings_response()
    youtube = youtube_settings_response()
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "build": build,
        "runtime": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "container": Path("/.dockerenv").exists(),
        },
        "ai": {
            "provider": config.provider,
            "model": config.model,
            "fallback_1": config.fallback_1,
            "fallback_2": config.fallback_2,
            "configured": config.configured,
            "base_url_configured": bool(config.base_url.strip()),
            "provider_keys_set": {
                provider: config.key_is_saved(provider)
                for provider in (
                    "gemini",
                    "openai",
                    "anthropic",
                    "openrouter_auto",
                    "openrouter_free",
                    "ollama",
                    "custom",
                )
            },
        },
        "integrations": {
            "lastfm": {
                "configured": bool(lastfm.get("configured")),
                "source": str(lastfm.get("source", "")),
            },
            "youtube_music": {
                "credentials_configured": bool(youtube.get("configured")),
                "oauth_token_present": YOUTUBE_TOKEN_PATH.exists(),
            },
        },
        "library": _database_metadata(),
        "logging": {
            "log_directory": "data/logs",
            "max_bytes_per_file": LOG_MAX_BYTES,
            "backup_count": LOG_BACKUP_COUNT,
        },
    }


def build_diagnostic_archive() -> bytes:
    """Build a sanitized ZIP report containing metadata and recent rotating logs."""
    secret_values = _known_secret_values()
    payload = sanitize_data(_diagnostic_payload(), secret_values=secret_values)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "diagnostics.json",
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        )
        archive.writestr(
            "README.txt",
            "PlaylistMuse diagnostic report\n\n"
            "Attach this ZIP to a GitHub bug report. PlaylistMuse removes known credentials "
            "and common secret formats before creating the archive. Review the files before "
            "sharing if your environment has additional sensitive values.\n",
        )
        for index in range(LOG_BACKUP_COUNT + 1):
            path = LOG_PATH if index == 0 else Path(f"{LOG_PATH}.{index}")
            if not path.exists():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            sanitized = sanitize_text(text, secret_values=secret_values)
            archive.writestr(f"logs/{path.name}", sanitized)
    return output.getvalue()


@router.post("/frontend-error")
async def report_frontend_error(report: FrontendErrorReport) -> dict[str, str | bool]:
    reference = new_error_reference()
    secret_values = _known_secret_values()
    LOGGER.warning(
        "frontend_error reference=%s kind=%s path=%s source=%s line=%s column=%s message=%s stack=%s",
        reference,
        sanitize_text(report.kind, secret_values=secret_values),
        sanitize_text(report.path, secret_values=secret_values),
        sanitize_text(report.source, secret_values=secret_values),
        report.line,
        report.column,
        sanitize_text(report.message, secret_values=secret_values),
        sanitize_text(report.stack, secret_values=secret_values),
    )
    return {"accepted": True, "error_reference": reference}


@router.get("/report")
async def download_diagnostic_report() -> StreamingResponse:
    payload = build_diagnostic_archive()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    filename = f"playlistmuse-diagnostics-{stamp}.zip"
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/storage")
async def get_storage() -> dict[str, Any]:
    return _storage_payload()


@router.post("/storage/clear-cache")
async def clear_cache() -> dict[str, Any]:
    bytes_freed = 0
    for _name, path, _ttl_days in CACHE_FILES:
        try:
            bytes_freed += path.stat().st_size
        except OSError:
            continue
        path.unlink(missing_ok=True)
    payload = _storage_payload()
    payload["cleared"] = True
    payload["bytes_freed"] = bytes_freed
    return payload


__all__ = [
    "ERROR_REFERENCE_HEADER",
    "LOG_DIR",
    "LOG_PATH",
    "build_diagnostic_archive",
    "configure_diagnostics_logging",
    "diagnostics_middleware",
    "new_error_reference",
    "router",
    "sanitize_data",
    "sanitize_text",
]
