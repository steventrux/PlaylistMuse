"""Build metadata exposed to the UI and FastAPI documentation."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass

from fastapi import APIRouter

REPOSITORY_URL = "https://github.com/steventrux/PlaylistMuse"
_VALID_CHANNELS = {"stable", "beta", "dev"}

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


def current_build_info() -> BuildInfo:
    """Return metadata baked into the running build through environment variables."""
    version = _clean(os.getenv("PLAYLISTMUSE_VERSION")) or "dev"
    requested_channel = _clean(os.getenv("PLAYLISTMUSE_CHANNEL")).lower()
    channel = requested_channel if requested_channel in _VALID_CHANNELS else _infer_channel(version)
    commit = _clean(os.getenv("PLAYLISTMUSE_GIT_SHA"))
    if commit.lower() in {"unknown", "none"}:
        commit = ""
    short_commit = commit[:7] if commit else ""

    label = _version_label(version)
    suffix = short_commit if channel == "dev" and short_commit else channel
    display = label if label == suffix else f"{label} · {suffix}"

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
