"""Build metadata exposed to the UI and FastAPI documentation."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from backend.source_revision import git_revision
from backend.version import APP_VERSION, REPOSITORY_URL

_VALID_CHANNELS = {"stable", "beta", "dev"}
_INVALID_COMMITS = {"", "unknown", "none", "local"}
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_SOURCE_GIT_DIR = _PROJECT_ROOT / ".git"

router = APIRouter()


@dataclass(frozen=True)
class BuildInfo:
    version: str
    channel: str
    commit: str
    display: str
    dirty: bool = False
    repository_url: str = REPOSITORY_URL


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _version_label(version: str) -> str:
    if not version:
        return "dev"
    if version.lower() in {"dev", "ci"} or version.startswith("v"):
        return version
    return f"v{version}"


def _infer_channel(version: str) -> str:
    lowered = version.lower()
    if any(token in lowered for token in ("beta", "alpha", "rc")):
        return "beta"
    if lowered in {"", "dev", "ci"} or "dev" in lowered:
        return "dev"
    return "stable"


def _source_git_dir() -> Path:
    configured = _clean(os.getenv("PLAYLISTMUSE_SOURCE_GIT_DIR"))
    return Path(configured) if configured else _DEFAULT_SOURCE_GIT_DIR


# Snapshot the checkout revision when the backend starts. A later git pull on the
# host must not make a still-running container claim to be serving newer code.
_STARTUP_SOURCE_COMMIT = git_revision(_source_git_dir())


def _running_commit() -> str:
    commit = _clean(os.getenv("PLAYLISTMUSE_GIT_SHA"))
    if commit.lower() in _INVALID_COMMITS:
        commit = ""
    if not commit:
        commit = _STARTUP_SOURCE_COMMIT
    return commit[:7] if commit else ""


def _running_build_is_dirty() -> bool:
    """Whether the image was built from a checkout with uncommitted local changes.

    This is a build-time snapshot (baked in via the PLAYLISTMUSE_GIT_DIRTY build arg,
    computed on the host — see scripts/vps-smoke-test.sh), not something re-derived at
    container startup: unlike the checkout revision, there's no lightweight way to detect
    an uncommitted diff from just the mounted `.git/HEAD` and `.git/refs`.
    """
    return _clean(os.getenv("PLAYLISTMUSE_GIT_DIRTY")).lower() in {"1", "true", "yes"}


def current_build_info() -> BuildInfo:
    """Return metadata for the exact build currently serving the application."""
    requested_channel = _clean(os.getenv("PLAYLISTMUSE_CHANNEL")).lower()
    configured_version = _clean(os.getenv("PLAYLISTMUSE_VERSION"))
    version = (
        configured_version
        or (APP_VERSION if requested_channel == "stable" else "dev")
    )
    channel = requested_channel if requested_channel in _VALID_CHANNELS else _infer_channel(version)
    short_commit = _running_commit()
    dirty = _running_build_is_dirty()

    label = _version_label(version)
    base_display = (
        f"{label} · {short_commit}"
        if channel == "dev" and short_commit
        else label
    )
    display = f"{base_display} (local)" if dirty else base_display

    return BuildInfo(
        version=version,
        channel=channel,
        commit=short_commit,
        display=display,
        dirty=dirty,
    )


@router.get("/version")
def get_version() -> dict[str, Any]:
    """Return the version, release channel and source revision of this running build."""
    return asdict(current_build_info())
