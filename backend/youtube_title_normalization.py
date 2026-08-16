"""Normalize catalogue title credits for matching."""

from __future__ import annotations


_SUFFIXES = (
    " (feat. ",
    " (feat ",
    " (ft. ",
    " (ft ",
    " (featuring ",
    " [feat. ",
    " [feat ",
    " [ft. ",
    " [ft ",
    " [featuring ",
    " - feat. ",
    " - ft. ",
    " - featuring ",
    " feat. ",
    " ft. ",
)


def base_title(value: str) -> str:
    text = " ".join(str(value).split())
    folded = text.casefold()
    for marker in _SUFFIXES:
        position = folded.rfind(marker)
        if position > 0:
            return text[:position].rstrip(" -([")
    return text
