"""PlaylistMuse backend package bootstrap."""

from __future__ import annotations

from functools import wraps
from typing import Any


def _install_metadata_constraint_capture() -> None:
    """Capture prompt constraints before any playlist draft is generated.

    The public generation function is wrapped once at package import time so every
    workflow that already uses it—initial generation, replenishment and replacement—
    shares the same request-scoped metadata-validation context without duplicating
    endpoint logic.
    """
    from backend import llm
    from backend.metadata_validation import activate_constraints_from_prompt

    original = llm.generate_playlist_draft
    if getattr(original, "_playlistmuse_metadata_capture", False):
        return

    @wraps(original)
    async def wrapped_generate_playlist_draft(
        config: Any,
        prompt: str,
        count: int,
    ) -> dict[str, Any]:
        activate_constraints_from_prompt(prompt)
        return await original(config, prompt, count)

    wrapped_generate_playlist_draft._playlistmuse_metadata_capture = True  # type: ignore[attr-defined]
    llm.generate_playlist_draft = wrapped_generate_playlist_draft


_install_metadata_constraint_capture()
