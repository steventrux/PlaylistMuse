"""MusicBrainz-backed metadata lookup and phase-one constraint validation."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal

import httpx

API_ROOT = "https://musicbrainz.org/ws/2"
USER_AGENT = "PlaylistMuse/0.7 (https://github.com/steventrux/PlaylistMuse)"
DEFAULT_TTL_SECONDS = 90 * 24 * 60 * 60
RECENT_TTL_SECONDS = 7 * 24 * 60 * 60
NEGATIVE_TTL_SECONDS = 24 * 60 * 60
MIN_MATCH_SCORE = 0.78
HIGH_MATCH_SCORE = 0.90
_REQUEST_LOCK = asyncio.Lock()
_LAST_REQUEST_AT = 0.0

ValidationStatus = Literal["valid", "invalid", "unknown"]


@dataclass(slots=True)
class MetadataConstraints:
    release_year: int | None = None
    artist_country: str | None = None

    @property
    def active(self) -> bool:
        return self.release_year is not None or self.artist_country is not None


@dataclass(slots=True)
class TrackMetadata:
    artist: str
    title: str
    recording_mbid: str | None = None
    release_group_mbid: str | None = None
    isrcs: list[str] = field(default_factory=list)
    original_release_date: str | None = None
    original_release_year: int | None = None
    artist_country: str | None = None
    artist_area: str | None = None
    match_score: float = 0.0
    confidence: str = "low"
    source: str = "musicbrainz"
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ValidationResult:
    status: ValidationStatus
    violations: list[str]
    metadata: TrackMetadata


_YEAR_PATTERNS = (
    re.compile(r"\b(?:released?|published?|issued?|from|of|del|dell['’]?anno)\s+(?:in\s+)?(19\d{2}|20\d{2})\b", re.I),
    re.compile(r"\b(?:only|solo|soltanto|esclusivamente)\s+(?:from\s+|del\s+)?(19\d{2}|20\d{2})\b", re.I),
    re.compile(r"\b(19\d{2}|20\d{2})\s+(?:only|solo|soltanto|esclusivamente)\b", re.I),
)
_COUNTRY_PATTERNS = {
    "IT": re.compile(r"\b(?:italian artists?|artists? from italy|artisti italiani|cantanti italiani)\b", re.I),
}


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value).casefold())
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[a-z0-9]+", plain))


def extract_metadata_constraints(prompt: str) -> MetadataConstraints:
    normalized = " ".join(str(prompt).split())
    year = None
    for pattern in _YEAR_PATTERNS:
        match = pattern.search(normalized)
        if match:
            year = int(match.group(1))
            break
    country = next(
        (code for code, pattern in _COUNTRY_PATTERNS.items() if pattern.search(normalized)),
        None,
    )
    return MetadataConstraints(release_year=year, artist_country=country)


def _cache_path() -> Path:
    root = Path(os.getenv("PLAYLISTMUSE_DATA_DIR", "data"))
    return root / "metadata_cache.sqlite3"


def _connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or _cache_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS track_metadata_cache (
            cache_key TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            expires_at REAL NOT NULL
        )
        """
    )
    return connection


def _cache_key(artist: str, title: str) -> str:
    return f"{_normalize(artist)}|{_normalize(title)}"


def _read_cache(artist: str, title: str, *, path: Path | None = None) -> TrackMetadata | None:
    with _connect(path) as connection:
        row = connection.execute(
            "SELECT payload, expires_at FROM track_metadata_cache WHERE cache_key = ?",
            (_cache_key(artist, title),),
        ).fetchone()
        if not row or float(row["expires_at"]) <= time.time():
            return None
        return TrackMetadata(**json.loads(str(row["payload"])))


def _write_cache(metadata: TrackMetadata, *, ttl: int, path: Path | None = None) -> None:
    with _connect(path) as connection:
        connection.execute(
            """
            INSERT INTO track_metadata_cache(cache_key, payload, expires_at)
            VALUES (?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
              payload = excluded.payload,
              expires_at = excluded.expires_at
            """,
            (
                _cache_key(metadata.artist, metadata.title),
                json.dumps(asdict(metadata), ensure_ascii=False),
                time.time() + ttl,
            ),
        )


def _artist_credit(recording: dict[str, Any]) -> str:
    credits = recording.get("artist-credit")
    if not isinstance(credits, list):
        return ""
    return "".join(
        str(item.get("name", "")) + str(item.get("joinphrase", ""))
        for item in credits
        if isinstance(item, dict)
    ).strip()


def _score_recording(recording: dict[str, Any], artist: str, title: str) -> float:
    title_score = SequenceMatcher(None, _normalize(title), _normalize(recording.get("title", ""))).ratio()
    artist_score = SequenceMatcher(None, _normalize(artist), _normalize(_artist_credit(recording))).ratio()
    api_score = max(0.0, min(1.0, float(recording.get("score", 0)) / 100.0))
    return round((title_score * 0.45) + (artist_score * 0.40) + (api_score * 0.15), 4)


def _date_key(value: str | None) -> tuple[int, int, int]:
    parts = str(value or "").split("-")
    try:
        return tuple(int(parts[index]) if index < len(parts) else 1 for index in range(3))  # type: ignore[return-value]
    except ValueError:
        return (9999, 12, 31)


def _metadata_from_recording(recording: dict[str, Any], artist: str, title: str) -> TrackMetadata:
    score = _score_recording(recording, artist, title)
    releases = [release for release in recording.get("releases", []) if isinstance(release, dict)]
    dated = [release for release in releases if str(release.get("date", "")).strip()]
    earliest = min(dated, key=lambda item: _date_key(str(item.get("date")))) if dated else {}
    release_group = earliest.get("release-group") if isinstance(earliest.get("release-group"), dict) else {}
    credits = recording.get("artist-credit") if isinstance(recording.get("artist-credit"), list) else []
    artist_entity = next(
        (item.get("artist") for item in credits if isinstance(item, dict) and isinstance(item.get("artist"), dict)),
        {},
    )
    area = artist_entity.get("area") if isinstance(artist_entity.get("area"), dict) else {}
    begin_area = artist_entity.get("begin-area") if isinstance(artist_entity.get("begin-area"), dict) else {}
    release_date = str(earliest.get("date", "")).strip() or None
    return TrackMetadata(
        artist=artist,
        title=title,
        recording_mbid=str(recording.get("id", "")).strip() or None,
        release_group_mbid=str(release_group.get("id", "")).strip() or None,
        isrcs=[str(value) for value in recording.get("isrcs", []) if str(value).strip()],
        original_release_date=release_date,
        original_release_year=int(release_date[:4]) if release_date and release_date[:4].isdigit() else None,
        artist_country=str(artist_entity.get("country", "")).upper() or None,
        artist_area=str(area.get("name") or begin_area.get("name") or "").strip() or None,
        match_score=score,
        confidence="high" if score >= HIGH_MATCH_SCORE else "medium" if score >= MIN_MATCH_SCORE else "low",
    )


async def _rate_limited_get(client: httpx.AsyncClient, params: dict[str, str]) -> httpx.Response:
    global _LAST_REQUEST_AT
    async with _REQUEST_LOCK:
        delay = 1.05 - (time.monotonic() - _LAST_REQUEST_AT)
        if delay > 0:
            await asyncio.sleep(delay)
        response = await client.get(f"{API_ROOT}/recording", params=params)
        _LAST_REQUEST_AT = time.monotonic()
        return response


async def lookup_track_metadata(
    artist: str,
    title: str,
    *,
    client: httpx.AsyncClient | None = None,
    cache_path: Path | None = None,
) -> TrackMetadata:
    cached = _read_cache(artist, title, path=cache_path)
    if cached is not None:
        return cached
    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(8.0),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        query = f'recording:"{title}" AND artist:"{artist}"'
        response = await _rate_limited_get(
            active_client,
            {"query": query, "fmt": "json", "limit": "8", "inc": "artists+releases+release-groups+isrcs"},
        )
        response.raise_for_status()
        recordings = response.json().get("recordings", [])
        candidates = [item for item in recordings if isinstance(item, dict)]
        if not candidates:
            metadata = TrackMetadata(artist=artist, title=title, warnings=["No MusicBrainz match"])
            _write_cache(metadata, ttl=NEGATIVE_TTL_SECONDS, path=cache_path)
            return metadata
        metadata = max(
            (_metadata_from_recording(item, artist, title) for item in candidates),
            key=lambda item: item.match_score,
        )
        if metadata.match_score < MIN_MATCH_SCORE:
            metadata.warnings.append("MusicBrainz match confidence is too low")
        ttl = RECENT_TTL_SECONDS if metadata.original_release_year and metadata.original_release_year >= time.gmtime().tm_year - 1 else DEFAULT_TTL_SECONDS
        _write_cache(metadata, ttl=ttl, path=cache_path)
        return metadata
    except (httpx.HTTPError, ValueError, TypeError, sqlite3.Error) as error:
        return TrackMetadata(artist=artist, title=title, warnings=[f"Metadata lookup unavailable: {type(error).__name__}"])
    finally:
        if owns_client:
            await active_client.aclose()


def validate_metadata(metadata: TrackMetadata, constraints: MetadataConstraints) -> ValidationResult:
    violations: list[str] = []
    unknown = False
    if metadata.match_score < MIN_MATCH_SCORE:
        unknown = True
    if constraints.release_year is not None:
        if metadata.original_release_year is None:
            unknown = True
        elif metadata.original_release_year != constraints.release_year:
            violations.append(
                f"release year {metadata.original_release_year} does not match {constraints.release_year}"
            )
    if constraints.artist_country is not None:
        if not metadata.artist_country:
            unknown = True
        elif metadata.artist_country.upper() != constraints.artist_country.upper():
            violations.append(
                f"artist country {metadata.artist_country} does not match {constraints.artist_country}"
            )
    status: ValidationStatus = "invalid" if violations else "unknown" if unknown else "valid"
    return ValidationResult(status=status, violations=violations, metadata=metadata)


async def validate_candidate(
    candidate: dict[str, Any],
    constraints: MetadataConstraints,
    *,
    client: httpx.AsyncClient | None = None,
    cache_path: Path | None = None,
) -> ValidationResult:
    artist = str(candidate.get("artist", candidate.get("artists", ""))).strip()
    title = str(candidate.get("title", "")).strip()
    metadata = await lookup_track_metadata(artist, title, client=client, cache_path=cache_path)
    return validate_metadata(metadata, constraints)
