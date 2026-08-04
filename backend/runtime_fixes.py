"""Backward-compatible bootstrap hook for older integrations."""

from __future__ import annotations


def install_pre_generation_fixes() -> None:
    """Runtime corrections now live in their owning modules."""
    return None
