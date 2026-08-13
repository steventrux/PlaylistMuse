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
    preference_rule = ""
    if normalized == "popular":
        preference_rule = (
            " The request explicitly favors popular or recognizable songs. Among equally "
            "valid candidates, favor higher Recco popularity values."
        )
    elif normalized == "less_known":
        preference_rule = (
            " The request explicitly favors lesser-known songs. Among equally valid "
            "candidates, favor lower known Recco popularity values. Missing popularity is "
            "neutral and is not evidence that a song is obscure."
        )

    lines: list[str] = []
    for candidate in usable:
        artist = str(candidate.get("artist", "Unknown artist"))
        title = str(candidate.get("title", "Unknown track"))
        score = candidate.get("popularity")
        suffix = f" [Recco popularity: {score}]" if score is not None else ""
        lines.append(f"- {artist} — {title}{suffix}")

    return (
        "\n\nRECCOBEATS DISCOVERY: use these catalogue-backed candidates only when they "
        "satisfy the original request. When selecting one, preserve the supplied artist and "
        "title. Hard constraints, quotas, recording rules and creative fit remain "
        "authoritative. Popularity is a soft preference only."
        f"{preference_rule}\n"
        + "\n".join(lines)
    )
