"""Shared Unicode-safe text normalization helpers."""

from __future__ import annotations

import unicodedata


def normalize_identity(value: str) -> str:
    """Normalize identity text while preserving letters and numbers from every script."""
    decomposed = unicodedata.normalize("NFKD", str(value).casefold())
    without_marks = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    separated = "".join(char if char.isalnum() else " " for char in without_marks)
    return " ".join(separated.split())
