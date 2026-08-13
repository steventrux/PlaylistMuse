"""Prompt guidance for ReccoBeats discovery candidates."""

from __future__ import annotations

from typing import Any


def popularity_preference(intent: Any) -> str:
    return str(intent.preference) if getattr(intent, "active", False) else "neutral"


def reccobeats_guidance(
    candidates: list[dict[str, Any]],
    preference: str = "neutral",
) -> str:
    usable = [
        item
        for item in candidates[:24]
        if str(item.get("artist", "")).strip()
        and str(item.get("title", "")).strip()
    ]
    if not usable:
        return ""

    normalized = str(preference).strip().casefold()
    rule = ""
    identity_rule = ""
    if normalized == "popular":
        rule = (
            " The request explicitly favors popular or recognizable songs. This list was "
            "ranked from a broader ReccoBeats pool so higher known popularity values appear "
            "first."
        )
        identity_rule = (
            " Use these catalogue-backed entries as the primary source of song identities. "
            "When enough entries satisfy all request constraints and the creative brief, most "
            "returned tracks should come from this list. Use an unlisted song only to fill a "
            "real gap after unsuitable listed candidates are skipped."
        )
    elif normalized == "less_known":
        rule = (
            " The request explicitly favors lesser-known songs. This list was ranked from a "
            "broader ReccoBeats pool so lower known popularity values appear first. A missing "
            "popularity value is neutral and must not be treated as proof of obscurity."
        )
        identity_rule = (
            " Use these catalogue-backed entries as the primary source of song identities. "
            "When enough entries satisfy all request constraints and the creative brief, most "
            "returned tracks should come from this list. Do not replace a suitable listed "
            "track with a more familiar unlisted song merely because it is easier to recall. "
            "Use an unlisted song only to fill a real gap after unsuitable listed candidates "
            "are skipped."
        )

    lines: list[str] = []
    for item in usable:
        score = item.get("popularity")
        suffix = f" [Recco popularity: {score}]" if score is not None else ""
        lines.append(f"- {item.get('artist')} — {item.get('title')}{suffix}")

    base = (
        "\n\nRECCOBEATS DISCOVERY: the following catalogue-backed candidates are discovery "
        "suggestions, not pre-approved selections. Every hard constraint, artist quota, "
        "recording rule, creative requirement and forbidden/already-attempted list still "
        "applies. When selecting one, preserve its supplied artist and title exactly. Never "
        "include a song only because it appears in this pool. Popularity is a soft preference "
        "and never overrides eligibility or creative fit."
    )
    return base + rule + identity_rule + "\n" + "\n".join(lines)
