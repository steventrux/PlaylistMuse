"""Deterministic extraction for explicit artist quota wording."""

from __future__ import annotations

import re
from typing import Any

from backend.text_normalization import normalize_identity

_STRICT_MAJORITY_ARTIST_PATTERNS = (
    re.compile(
        r"\bpi[uù]\s+della\s+met[aà]\s+(?:dei|degli|delle)?\s*"
        r"(?:brani|canzoni|tracce|pezzi)?\s*(?:deve|devono)?\s*(?:essere|provenire)?\s*"
        r"(?:di|dei|degli|delle)\s+([^,;.!\n]{1,120})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bmore\s+than\s+half\s+(?:of\s+)?(?:the\s+)?(?:songs|tracks)?\s*"
        r"(?:must\s+be\s+)?(?:by|from)\s+([^,;.!\n]{1,120})",
        re.IGNORECASE,
    ),
)


def _clean_artist(value: str) -> str:
    return " ".join(value.split()).strip(" \t\r\n.,;:!?\"'“”")[:120]


def _append_unique(values: Any, addition: str) -> list[str]:
    current = [str(item).strip() for item in values] if isinstance(values, list) else []
    existing = {normalize_identity(item) for item in current}
    key = normalize_identity(addition)
    if key and key not in existing:
        current.append(addition)
    return current


def augment_explicit_artist_quotas(
    prompt: str,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Add locally provable strict-majority quotas without overriding AI fields."""
    result = dict(payload) if isinstance(payload, dict) else {}
    artist = ""
    for pattern in _STRICT_MAJORITY_ARTIST_PATTERNS:
        match = pattern.search(prompt)
        if match:
            artist = _clean_artist(match.group(1))
            break
    if not artist:
        return result

    result["quota_artists"] = _append_unique(result.get("quota_artists"), artist)
    if result.get("minimum_allowed_artist_ratio") is None:
        result["minimum_allowed_artist_ratio"] = 0.5

    confidence = dict(result.get("field_confidence") or {})
    confidence["quota_artists"] = max(float(confidence.get("quota_artists", 0.0)), 0.99)
    confidence["minimum_allowed_artist_ratio"] = max(
        float(confidence.get("minimum_allowed_artist_ratio", 0.0)),
        0.99,
    )
    result["field_confidence"] = confidence
    return result
