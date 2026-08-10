"""Build metadata exposed to the UI and FastAPI documentation."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

from fastapi import APIRouter

from backend.source_revision import git_revision

REPOSITORY_URL = "https://github.com/steventrux/PlaylistMuse"
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


def current_build_info() -> BuildInfo:
    """Return metadata for the exact build currently serving the application."""
    version = _clean(os.getenv("PLAYLISTMUSE_VERSION")) or "dev"
    requested_channel = _clean(os.getenv("PLAYLISTMUSE_CHANNEL")).lower()
    channel = requested_channel if requested_channel in _VALID_CHANNELS else _infer_channel(version)
    short_commit = _running_commit()

    label = _version_label(version)
    display = (
        f"{label} · {short_commit}"
        if channel == "dev" and short_commit
        else label
    )

    return BuildInfo(
        version=version,
        channel=channel,
        commit=short_commit,
        display=display,
    )


@router.get("/version")
def get_version() -> dict[str, str]:
    """Return the version, release channel and source revision of this running build."""
    return asdict(current_build_info())
