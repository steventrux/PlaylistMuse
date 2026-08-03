"""MusicBrainz-backed metadata lookup and hard-constraint validation."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import time
import unicodedata
from contextvars import ContextVar
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
    release_year_from: int | None = None
    release_year_to: int | None = None
    artist_country: str | None = None
    allowed_artists: list[str] = field(default_factory=list)
    excluded_artists: list[str] = field(default_factory=list)
    allowed_albums: list[str] = field(default_factory=list)
    excluded_albums: list[str] = field(default_factory=list)

    @property
    def artist_name(self) -> str | None:
        return self.allowed_artists[0] if len(self.allowed_artists) == 1 else None

    @property
    def album_name(self) -> str | None:
        return self.allowed_albums[0] if len(self.allowed_albums) == 1 else None

    @property
    def active(self) -> bool:
        return any((self.release_year is not None, self.release_year_from is not None, self.release_year_to is not None, self.artist_country is not None, bool(self.allowed_artists), bool(self.excluded_artists), bool(self.allowed_albums), bool(self.excluded_albums)))


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
    matched_artist: str | None = None
    release_titles: list[str] = field(default_factory=list)
    match_score: float = 0.0
    confidence: str = "low"
    source: str = "musicbrainz"
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ValidationResult:
    status: ValidationStatus
    violations: list[str]
    metadata: TrackMetadata


_ACTIVE_CONSTRAINTS: ContextVar[MetadataConstraints] = ContextVar("playlistmuse_metadata_constraints", default=MetadataConstraints())
_SIMILARITY_RE = re.compile(r"\b(?:come|simile(?:\s+a|\s+ai|\s+agli)?|ispirat[oaie]?\s+a|in\s+stile|con\s+sonorit[aà]|dal\s+sapore|tipo|like|similar\s+to|inspired\s+by|style|vibe|sound(?:ing)?\s+like)\b", re.I)
_YEAR_PATTERNS = (
    re.compile(r"\b(?:released?|published?|issued?|from|of|del|dell['’]?anno)\s+(?:in\s+)?(19\d{2}|20\d{2})\b", re.I),
    re.compile(r"\b(?:only|solo|soltanto|esclusivamente)\s+(?:from\s+|del\s+)?(19\d{2}|20\d{2})\b", re.I),
    re.compile(r"\b(19\d{2}|20\d{2})\s+(?:only|solo|soltanto|esclusivamente)\b", re.I),
)
_YEAR_RANGE_PATTERNS = (
    re.compile(r"\b(?:between|from|dal|dall['’]?|tra(?:\s+il)?)\s*(19\d{2}|20\d{2})\s*(?:and|e|to|al|a|-)\s*(19\d{2}|20\d{2})\b", re.I),
    re.compile(r"\b(19\d{2}|20\d{2})\s*[-–—]\s*(19\d{2}|20\d{2})\b"),
)
_DECADE_PATTERNS = (
    re.compile(r"\b(?:anni|années|años|anos|jahre|decade|décennie|década|年代)\s*['’]?(\d{2})\b", re.I),
    re.compile(r"\b(19\d0|20\d0)s\b", re.I),
)
_COUNTRY_PATTERNS = {"IT": re.compile(r"\b(?:italian artists?|artists? from italy|artisti italiani|cantanti italiani)\b", re.I)}
_DIRECT_ARTIST_PATTERNS = (
    re.compile(r"\b(?:musica|brani|canzoni|songs?|tracks?|music)\s+(?:di|dei|degli|delle|by|from)\s+([\wÀ-ÿ&.' -]{1,100}?)(?=\s+(?:per|for|pour|para|zum|für)\b|[.!?,;]|$)", re.I),
    re.compile(r"\b(?:solo|only|soltanto|esclusivamente)\s+(?:musica|brani|canzoni|songs?|tracks?)?\s*(?:di|dei|degli|delle|by|from)\s+([\wÀ-ÿ&.' -]{1,100})(?:[.!?,;]|$)", re.I),
)
_ALBUM_PATTERNS = (
    re.compile(r"\b(?:from|off|dall['’]?album|dall['’]?disco|album)\s+['\"]([^'\"]{1,180})['\"]", re.I),
    re.compile(r"\b(?:album|disco)\s+['\"]([^'\"]{1,180})['\"]\s+(?:only|solo|soltanto|esclusivamente)\b", re.I),
)


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value).casefold())
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[a-z0-9]+", plain))


def _clean_names(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        name = " ".join(str(value).split()).strip(" .,-")
        key = _normalize(name)
        if name and key and key not in seen:
            seen.add(key)
            cleaned.append(name[:180])
    return cleaned[:20]


def _clean_year(value: Any) -> int | None:
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if 1800 <= year <= 2200 else None


def constraints_from_payload(payload: dict[str, Any] | None, *, fallback: MetadataConstraints | None = None) -> MetadataConstraints:
    base = fallback or MetadataConstraints()
    if not isinstance(payload, dict) or str(payload.get("confidence", "")).casefold() == "low":
        return base
    release_year = _clean_year(payload.get("release_year")) or base.release_year
    year_from = _clean_year(payload.get("release_year_from")) or base.release_year_from
    year_to = _clean_year(payload.get("release_year_to")) or base.release_year_to
    if year_from is not None and year_to is not None and year_from > year_to:
        year_from, year_to = year_to, year_from
    country = str(payload.get("artist_country") or base.artist_country or "").upper().strip() or None
    return MetadataConstraints(
        release_year=release_year,
        release_year_from=year_from,
        release_year_to=year_to,
        artist_country=country,
        allowed_artists=_clean_names(payload.get("allowed_artists")) or list(base.allowed_artists),
        excluded_artists=_clean_names(payload.get("excluded_artists")) or list(base.excluded_artists),
        allowed_albums=_clean_names(payload.get("allowed_albums")) or list(base.allowed_albums),
        excluded_albums=_clean_names(payload.get("excluded_albums")) or list(base.excluded_albums),
    )


def extract_metadata_constraints(prompt: str) -> MetadataConstraints:
    normalized = " ".join(str(prompt).split())
    similarity = bool(_SIMILARITY_RE.search(normalized))
    year = year_from = year_to = None
    if not similarity:
        for pattern in _YEAR_RANGE_PATTERNS:
            match = pattern.search(normalized)
            if match:
                year_from, year_to = sorted((int(match.group(1)), int(match.group(2))))
                break
        if year_from is None:
            for pattern in _DECADE_PATTERNS:
                match = pattern.search(normalized)
                if match:
                    value = int(match.group(1))
                    year_from = value if value >= 1900 else 1900 + value
                    year_to = year_from + 9
                    break
        if year_from is None:
            for pattern in _YEAR_PATTERNS:
                match = pattern.search(normalized)
                if match:
                    year = int(match.group(1))
                    break
    country = next((code for code, pattern in _COUNTRY_PATTERNS.items() if pattern.search(normalized)), None)
    allowed_artists: list[str] = []
    if not similarity:
        for pattern in _DIRECT_ARTIST_PATTERNS:
            match = pattern.search(normalized)
            if match:
                allowed_artists = _clean_names([match.group(1)])
                break
    allowed_albums: list[str] = []
    if not similarity:
        for pattern in _ALBUM_PATTERNS:
            match = pattern.search(normalized)
            if match:
                allowed_albums = _clean_names([match.group(1)])
                break
    return MetadataConstraints(release_year=year, release_year_from=year_from, release_year_to=year_to, artist_country=country, allowed_artists=allowed_artists, allowed_albums=allowed_albums)


def activate_constraints_from_prompt(prompt: str) -> MetadataConstraints:
    constraints = extract_metadata_constraints(prompt)
    _ACTIVE_CONSTRAINTS.set(constraints)
    return constraints


def activate_constraints(constraints: MetadataConstraints) -> None:
    _ACTIVE_CONSTRAINTS.set(constraints)


def active_constraints() -> MetadataConstraints:
    return _ACTIVE_CONSTRAINTS.get()


def _cache_path() -> Path:
    root = Path(os.getenv("PLAYLISTMUSE_DATA_DIR", "data"))
    return root / "metadata_cache.sqlite3"


def _connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or _cache_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target)
    connection.row_factory = sqlite3.Row
    connection.execute("""CREATE TABLE IF NOT EXISTS track_metadata_cache (cache_key TEXT PRIMARY KEY, payload TEXT NOT NULL, expires_at REAL NOT NULL)""")
    return connection


def _cache_key(artist: str, title: str) -> str:
    return f"{_normalize(artist)}|{_normalize(title)}"


def _read_cache(artist: str, title: str, *, path: Path | None = None) -> TrackMetadata | None:
    with _connect(path) as connection:
        row = connection.execute("SELECT payload, expires_at FROM track_metadata_cache WHERE cache_key = ?", (_cache_key(artist, title),)).fetchone()
        if not row or float(row["expires_at"]) <= time.time():
            return None
        payload = json.loads(str(row["payload"]))
        payload.setdefault("matched_artist", None)
        payload.setdefault("release_titles", [])
        return TrackMetadata(**payload)


def _write_cache(metadata: TrackMetadata, *, ttl: int, path: Path | None = None) -> None:
    with _connect(path) as connection:
        connection.execute("""INSERT INTO track_metadata_cache(cache_key, payload, expires_at) VALUES (?, ?, ?) ON CONFLICT(cache_key) DO UPDATE SET payload = excluded.payload, expires_at = excluded.expires_at""", (_cache_key(metadata.artist, metadata.title), json.dumps(asdict(metadata), ensure_ascii=False), time.time() + ttl))


def _artist_credit(recording: dict[str, Any]) -> str:
    credits = recording.get("artist-credit")
    if not isinstance(credits, list):
        return ""
    return "".join(str(item.get("name", "")) + str(item.get("joinphrase", "")) for item in credits if isinstance(item, dict)).strip()


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
    artist_entity = next((item.get("artist") for item in credits if isinstance(item, dict) and isinstance(item.get("artist"), dict)), {})
    area = artist_entity.get("area") if isinstance(artist_entity.get("area"), dict) else {}
    begin_area = artist_entity.get("begin-area") if isinstance(artist_entity.get("begin-area"), dict) else {}
    release_date = str(earliest.get("date", "")).strip() or None
    release_titles = list(dict.fromkeys([str(release.get("title", "")).strip() for release in releases if str(release.get("title", "")).strip()] + ([str(release_group.get("title", "")).strip()] if str(release_group.get("title", "")).strip() else [])))
    return TrackMetadata(artist=artist, title=title, recording_mbid=str(recording.get("id", "")).strip() or None, release_group_mbid=str(release_group.get("id", "")).strip() or None, isrcs=[str(value) for value in recording.get("isrcs", []) if str(value).strip()], original_release_date=release_date, original_release_year=int(release_date[:4]) if release_date and release_date[:4].isdigit() else None, artist_country=str(artist_entity.get("country", "")).upper() or None, artist_area=str(area.get("name") or begin_area.get("name") or "").strip() or None, matched_artist=_artist_credit(recording) or None, release_titles=release_titles, match_score=score, confidence="high" if score >= HIGH_MATCH_SCORE else "medium" if score >= MIN_MATCH_SCORE else "low")


async def _rate_limited_get(client: httpx.AsyncClient, params: dict[str, str]) -> httpx.Response:
    global _LAST_REQUEST_AT
    async with _REQUEST_LOCK:
        delay = 1.05 - (time.monotonic() - _LAST_REQUEST_AT)
        if delay > 0:
            await asyncio.sleep(delay)
        response = await client.get(f"{API_ROOT}/recording", params=params)
        _LAST_REQUEST_AT = time.monotonic()
        return response


async def lookup_track_metadata(artist: str, title: str, *, client: httpx.AsyncClient | None = None, cache_path: Path | None = None) -> TrackMetadata:
    cached = _read_cache(artist, title, path=cache_path)
    if cached is not None:
        return cached
    owns_client = client is None
    active_client = client or httpx.AsyncClient(timeout=httpx.Timeout(8.0), headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        query = f'recording:"{title}" AND artist:"{artist}"'
        response = await _rate_limited_get(active_client, {"query": query, "fmt": "json", "limit": "8", "inc": "artists+releases+release-groups+isrcs"})
        response.raise_for_status()
        candidates = [item for item in response.json().get("recordings", []) if isinstance(item, dict)]
        if not candidates:
            metadata = TrackMetadata(artist=artist, title=title, warnings=["No MusicBrainz match"])
            _write_cache(metadata, ttl=NEGATIVE_TTL_SECONDS, path=cache_path)
            return metadata
        metadata = max((_metadata_from_recording(item, artist, title) for item in candidates), key=lambda item: item.match_score)
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


def _artist_matches(actual: str, expected: str) -> bool:
    actual_norm = _normalize(actual)
    expected_norm = _normalize(expected)
    if not actual_norm or not expected_norm:
        return False
    if actual_norm == expected_norm or f" {expected_norm} " in f" {actual_norm} ":
        return True
    return SequenceMatcher(None, actual_norm, expected_norm).ratio() >= 0.90


def _album_matches(actual: str, expected: str) -> bool:
    actual_norm = _normalize(actual)
    expected_norm = _normalize(expected)
    if not actual_norm or not expected_norm:
        return False
    if actual_norm == expected_norm:
        return True
    suffix = actual_norm[len(expected_norm):].strip() if actual_norm.startswith(expected_norm) else ""
    edition_terms = {"remaster", "remastered", "deluxe", "edition", "expanded", "anniversary", "reissue"}
    return bool(suffix) and all(token.isdigit() or token in edition_terms for token in suffix.split())


def validate_metadata(metadata: TrackMetadata, constraints: MetadataConstraints) -> ValidationResult:
    violations: list[str] = []
    unknown = metadata.match_score < MIN_MATCH_SCORE
    year = metadata.original_release_year
    if constraints.release_year is not None:
        if year is None:
            unknown = True
        elif year != constraints.release_year:
            violations.append(f"release year {year} does not match {constraints.release_year}")
    if constraints.release_year_from is not None:
        if year is None:
            unknown = True
        elif year < constraints.release_year_from:
            violations.append(f"release year {year} is before {constraints.release_year_from}")
    if constraints.release_year_to is not None:
        if year is None:
            unknown = True
        elif year > constraints.release_year_to:
            violations.append(f"release year {year} is after {constraints.release_year_to}")
    if constraints.artist_country is not None:
        if not metadata.artist_country:
            unknown = True
        elif metadata.artist_country.upper() != constraints.artist_country.upper():
            violations.append(f"artist country {metadata.artist_country} does not match {constraints.artist_country}")
    actual_artist = metadata.matched_artist or metadata.artist
    if constraints.allowed_artists:
        if not actual_artist:
            unknown = True
        elif not any(_artist_matches(actual_artist, expected) for expected in constraints.allowed_artists):
            violations.append(f"artist {actual_artist} is not in allowed artists")
    if any(actual_artist and _artist_matches(actual_artist, excluded) for excluded in constraints.excluded_artists):
        violations.append(f"artist {actual_artist} is excluded")
    if constraints.allowed_albums:
        if not metadata.release_titles:
            unknown = True
        elif not any(_album_matches(title, expected) for title in metadata.release_titles for expected in constraints.allowed_albums):
            violations.append("track is not listed on an allowed album")
    for excluded in constraints.excluded_albums:
        if any(_album_matches(title, excluded) for title in metadata.release_titles):
            violations.append(f"track is listed on excluded album {excluded}")
            break
    status: ValidationStatus = "invalid" if violations else "unknown" if unknown else "valid"
    return ValidationResult(status=status, violations=violations, metadata=metadata)


async def validate_candidate(candidate: dict[str, Any], constraints: MetadataConstraints, *, client: httpx.AsyncClient | None = None, cache_path: Path | None = None) -> ValidationResult:
    artist = str(candidate.get("artist", candidate.get("artists", ""))).strip()
    title = str(candidate.get("title", "")).strip()
    metadata = await lookup_track_metadata(artist, title, client=client, cache_path=cache_path)
    return validate_metadata(metadata, constraints)
