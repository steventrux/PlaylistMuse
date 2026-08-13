"""Prompt guidance for ReccoBeats discovery candidates."""
from __future__ import annotations
from typing import Any

def popularity_preference(intent: Any) -> str:
    return str(intent.preference) if getattr(intent, "active", False) else "neutral"

def reccobeats_guidance(candidates: list[dict[str, Any]], preference: str = "neutral") -> str:
    usable = [item for item in candidates[:24] if str(item.get("artist", "")).strip() and str(item.get("title", "")).strip()]
    if not usable:
        return ""
    normalized = str(preference).strip().casefold()
    rule = ""
    if normalized == "popular":
        rule = " The request explicitly favors popular or recognizable songs. Among equally valid candidates, favor higher Recco popularity values."
    elif normalized == "less_known":
        rule = " The request explicitly favors lesser-known songs. Among equally valid candidates, favor lower known Recco popularity values. A missing popularity value is neutral and must not be treated as proof of obscurity."
    lines = []
    for item in usable:
        score = item.get("popularity")
        suffix = f" [Recco popularity: {score}]" if score is not None else ""
        lines.append(f"- {item.get('artist')} — {item.get('title')}{suffix}")
    base = "\n\nRECCOBEATS DISCOVERY: the following catalogue-backed candidates are discovery suggestions, not pre-approved selections; every hard constraint, artist quota, recording rule, creative requirement and forbidden/already-attempted list remains authoritative. When selecting one, preserve the supplied artist and title. Never include a song only because it appears in this pool. Popularity is a soft preference and never overrides eligibility or creative fit."
    return base + rule + "\n" + "\n".join(lines)
