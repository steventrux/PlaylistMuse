"""MusicBrainz-backed metadata lookup and hard-constraint validation."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal

import httpx

from backend.musicbrainz_artist import lookup_artist_origin
from backend.musicbrainz_client import rate_limited_get
from backend.national_origin import infer_artist_country, normalize_country_to_iso
from backend.text_normalization import normalize_identity as _normalize
from backend.validation_fixes import effective_temporal_range
from backend.version import USER_AGENT

API_ROOT = "https://musicbrainz.org/ws/2"
DEFAULT_TTL_SECONDS = 90 * 24 * 60 * 60
RECENT_TTL_SECONDS = 7 * 24 * 60 * 60
NEGATIVE_TTL_SECONDS = 24 * 60 * 60
MIN_MATCH_SCORE = 0.78
HIGH_MATCH_SCORE = 0.90
MIN_CONSTRAINT_CONFIDENCE = 0.85
METADATA_CACHE_VERSION = "6"

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
    exception_tracks: list[dict[str, str]] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    field_confidence: dict[str, float] = field(default_factory=dict)
    artist_name: str | None = None
    album_name: str | None = None

    def __post_init__(self) -> None:
        if self.artist_name and not self.allowed_artists:
            self.allowed_artists = [self.artist_name]
        elif not self.artist_name and len(self.allowed_artists) == 1:
            self.artist_name = self.allowed_artists[0]
        if self.album_name and not self.allowed_albums:
            self.allowed_albums = [self.album_name]
        elif not self.album_name and len(self.allowed_albums) == 1:
            self.album_name = self.allowed_albums[0]

    @property
    def active(self) -> bool:
        return any(
            (
                self.release_year is not None,
                self.release_year_from is not None,
                self.release_year_to is not None,
                self.artist_country is not None,
                bool(self.allowed_artists),
                bool(self.excluded_artists),
                bool(self.allowed_albums),
                bool(self.excluded_albums),
                bool(self.exception_tracks),
            )
        )


@dataclass(slots=True)
class TrackMetadata:
    artist: str
    title: str
    recording_mbid: str | None = None
    artist_mbid: str | None = None
    release_group_mbid: str | None = None
    release_group_primary_type: str | None = None
    release_group_secondary_types: tuple[str, ...] = field(default_factory=tuple)
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


_ACTIVE_CONSTRAINTS: ContextVar[MetadataConstraints | None] = ContextVar(
    "playlistmuse_metadata_constraints",
    default=None,
)
_SIMILARITY_RE = re.compile(
    r"\b(?:come|simile(?:\s+a|\s+ai|\s+agli)?|ispirat[oaie]?\s+a|"
    r"in\s+stile|con\s+sonorit[aà]|dal\s+sapore|tipo|like|similar\s+to|"
    r"inspired\s+by|style|vibe|sound(?:ing)?\s+like)\b",
    re.I,
)
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
_DIRECT_ARTIST_PATTERNS = (
    re.compile(r"\b(?:musica|brani|canzoni|songs?|tracks?|music)\s+(?:di|dei|degli|delle|by|from)\s+([\wÀ-ÿ&.' -]{1,100}?)(?=\s+(?:per|for|pour|para|zum|für)\b|[.!?,;]|$)", re.I),
    re.compile(r"\b(?:solo|only|soltanto|esclusivamente)\s+(?:musica|brani|canzoni|songs?|tracks?)?\s*(?:di|dei|degli|delle|by|from)\s+([\wÀ-ÿ&.' -]{1,100})(?:[.!?,;]|$)", re.I),
)
_ALBUM_PATTERNS = (
    re.compile(r"\b(?:from|off|dall['’]?album|dall['’]?disco|album)\s+['\"]([^'\"]{1,180})['\"]", re.I),
    re.compile(r"\b(?:album|disco)\s+['\"]([^'\"]{1,180})['\"]\s+(?:only|solo|soltanto|esclusivamente)\b", re.I),
)


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


def _clean_exception_tracks(values: Any) -> list[dict[str, str]]:
    if not isinstance(values, list):
        return []
    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            continue
        artist = " ".join(str(value.get("artist", "")).split()).strip(" .,-")[:180]
        title = " ".join(str(value.get("title", "")).split()).strip(" .,-")[:220]
        key = f"{_normalize(artist)}|{_normalize(title)}"
        if artist and title and key not in seen:
            seen.add(key)
            cleaned.append({"artist": artist, "title": title})
    return cleaned[:20]


def _clean_contradictions(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [
        " ".join(str(value).split())[:300]
        for value in values[:20]
        if str(value).strip()
    ]


def _clean_year(value: Any) -> int | None:
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if 1800 <= year <= 2200 else None


def _confidence_map(payload: dict[str, Any]) -> dict[str, float]:
    raw = payload.get("field_confidence")
    result: dict[str, float] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            try:
                result[str(key)] = max(0.0, min(1.0, float(value)))
            except (TypeError, ValueError):
                continue
    if result:
        return result
    overall = str(payload.get("confidence", "")).casefold()
    legacy = {"high": 0.95, "medium": 0.80, "low": 0.0}.get(overall, 0.0)
    return dict.fromkeys(
        (
            "allowed_artists",
            "excluded_artists",
            "allowed_albums",
            "excluded_albums",
            "release_year",
            "release_year_from",
            "release_year_to",
            "artist_country",
            "exception_tracks",
        ),
        legacy,
    )


def constraints_from_payload(
    payload: dict[str, Any] | None,
    *,
    fallback: MetadataConstraints | None = None,
) -> MetadataConstraints:
    base = fallback or MetadataConstraints()
    if not isinstance(payload, dict):
        return base
    confidence = _confidence_map(payload)

    def trusted(field_name: str) -> bool:
        return confidence.get(field_name, 0.0) >= MIN_CONSTRAINT_CONFIDENCE

    interpreted_release_year = (
        _clean_year(payload.get("release_year"))
        if trusted("release_year")
        else None
    )
    interpreted_year_from = (
        _clean_year(payload.get("release_year_from"))
        if trusted("release_year_from")
        else None
    )
    interpreted_year_to = (
        _clean_year(payload.get("release_year_to"))
        if trusted("release_year_to")
        else None
    )

    if base.release_year is not None:
        release_year = base.release_year
        year_from = None
        year_to = None
    elif base.release_year_from is not None or base.release_year_to is not None:
        release_year = None
        year_from = base.release_year_from
        year_to = base.release_year_to
    else:
        release_year = interpreted_release_year
        year_from = interpreted_year_from
        year_to = interpreted_year_to
        if year_from is not None and year_to is not None and year_from > year_to:
            year_from, year_to = year_to, year_from

    country = base.artist_country
    if country is None and trusted("artist_country"):
        # The interpretation schema has no format instruction for this field, so the
        # LLM may write a free-text country name ("Italy") instead of the ISO code
        # MusicBrainz returns ("IT") -- normalize deterministically rather than
        # comparing the LLM's raw formatting later.
        country = normalize_country_to_iso(str(payload.get("artist_country") or ""))

    allowed_artists = list(base.allowed_artists)
    if trusted("allowed_artists"):
        allowed_artists = _clean_names(payload.get("allowed_artists")) or allowed_artists
    excluded_artists = list(base.excluded_artists)
    if trusted("excluded_artists"):
        excluded_artists = _clean_names(payload.get("excluded_artists")) or excluded_artists
    allowed_albums = list(base.allowed_albums)
    if trusted("allowed_albums"):
        allowed_albums = _clean_names(payload.get("allowed_albums")) or allowed_albums
    excluded_albums = list(base.excluded_albums)
    if trusted("excluded_albums"):
        excluded_albums = _clean_names(payload.get("excluded_albums")) or excluded_albums
    exception_tracks = list(base.exception_tracks)
    if trusted("exception_tracks"):
        exception_tracks = _clean_exception_tracks(payload.get("exception_tracks")) or exception_tracks

    return MetadataConstraints(
        release_year=release_year,
        release_year_from=year_from,
        release_year_to=year_to,
        artist_country=country,
        allowed_artists=allowed_artists,
        excluded_artists=excluded_artists,
        allowed_albums=allowed_albums,
        excluded_albums=excluded_albums,
        exception_tracks=exception_tracks,
        contradictions=_clean_contradictions(payload.get("contradictions")),
        field_confidence=confidence,
    )


def extract_metadata_constraints(prompt: str) -> MetadataConstraints:
    normalized = " ".join(str(prompt).split())
    similarity = bool(_SIMILARITY_RE.search(normalized))
    year = year_from = year_to = None
    if not similarity:
        effective_range = effective_temporal_range(normalized)
        if effective_range is not None:
            year_from, year_to = effective_range
        if year_from is None:
            for pattern in _YEAR_RANGE_PATTERNS:
                match = pattern.search(normalized)
                if match:
                    year_from, year_to = sorted(
                        (int(match.group(1)), int(match.group(2)))
                    )
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
    country = infer_artist_country(normalized) if not similarity else None
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
    return MetadataConstraints(
        release_year=year,
        release_year_from=year_from,
        release_year_to=year_to,
        artist_country=country,
        allowed_artists=allowed_artists,
        allowed_albums=allowed_albums,
    )


def activate_constraints_from_prompt(prompt: str) -> MetadataConstraints:
    constraints = extract_metadata_constraints(prompt)
    _ACTIVE_CONSTRAINTS.set(constraints)
    return constraints


def activate_constraints(constraints: MetadataConstraints) -> None:
    _ACTIVE_CONSTRAINTS.set(constraints)


def active_constraints() -> MetadataConstraints:
    return _ACTIVE_CONSTRAINTS.get() or MetadataConstraints()


def _cache_path() -> Path:
    root = Path(os.getenv("PLAYLISTMUSE_DATA_DIR", "data"))
    return root / "metadata_cache.sqlite3"


def _connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or _cache_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE IF NOT EXISTS track_metadata_cache (
        cache_key TEXT PRIMARY KEY, payload TEXT NOT NULL, expires_at REAL NOT NULL)"""
    )
    return connection


def _cache_key(artist: str, title: str) -> str:
    """Version cache entries when metadata interpretation semantics change."""
    return (
        f"{METADATA_CACHE_VERSION}|{_normalize(artist)}|"
        f"{_normalize(title)}"
    )


def _read_cache(
    artist: str,
    title: str,
    *,
    path: Path | None = None,
) -> TrackMetadata | None:
    with _connect(path) as connection:
        row = connection.execute(
            "SELECT payload, expires_at FROM track_metadata_cache WHERE cache_key = ?",
            (_cache_key(artist, title),),
        ).fetchone()
        if not row or float(row["expires_at"]) <= time.time():
            return None
        payload = json.loads(str(row["payload"]))
        payload.setdefault("artist_mbid", None)
        payload.setdefault("matched_artist", None)
        payload.setdefault("release_titles", [])
        payload.setdefault("release_group_primary_type", None)
        payload.setdefault("release_group_secondary_types", [])
        return TrackMetadata(**payload)


def _metadata_ttl(metadata: TrackMetadata) -> int:
    return (
        RECENT_TTL_SECONDS
        if metadata.original_release_year
        and metadata.original_release_year >= time.gmtime().tm_year - 1
        else DEFAULT_TTL_SECONDS
    )


def _write_cache(
    metadata: TrackMetadata,
    *,
    ttl: int,
    path: Path | None = None,
) -> None:
    with _connect(path) as connection:
        connection.execute(
            """INSERT INTO track_metadata_cache(cache_key, payload, expires_at)
            VALUES (?, ?, ?) ON CONFLICT(cache_key) DO UPDATE SET
            payload = excluded.payload, expires_at = excluded.expires_at""",
            (
                _cache_key(metadata.artist, metadata.title),
                json.dumps(asdict(metadata), ensure_ascii=False),
                time.time() + ttl,
            ),
        )


_TITLE_EDITION_SUFFIX_TERMS = r"remaster(?:ed)?|radio\s+edit|\blive\b|\w+\s+version"
_TITLE_EDITION_BRACKET_SUFFIX_RE = re.compile(
    rf"\s*[\[(][^\])]*(?:{_TITLE_EDITION_SUFFIX_TERMS})[^\])]*[\])]\s*$",
    re.I,
)
_TITLE_EDITION_DASH_SUFFIX_RE = re.compile(
    rf"\s*[-–—]\s*(?:\d{{4}}\s+)?(?:{_TITLE_EDITION_SUFFIX_TERMS})\b.*$",
    re.I,
)


def _strip_title_edition_suffix(title: str) -> str:
    """Strip a trailing edition/version descriptor before building a MusicBrainz query.

    A YouTube-resolved title like "Summer of 69 (Classic Version)" or "Song (2011
    Remastered)" can make MusicBrainz's search match a specific reissue/rerelease
    instead of the true original recording, giving the wrong release year for hard
    constraint validation. This only cleans the *search query text* passed to
    MusicBrainz -- the candidate's actual title (what ends up in the playlist) is
    never touched, and the original title is still what gets returned in warnings/etc.

    Deliberately separate from backend/playlist_ordering.py's own, similarly-named
    suffix stripping: that one specifically tries both the exact and stripped title and
    keeps whichever gives an earlier year, which this single best-effort clean would
    interfere with if shared. This one is a single clean applied once, since
    validate_candidate() already has its own historical-probe fallback for ambiguous
    cases (see _historical_probe_cutoff).
    """
    cleaned = str(title).strip()
    for pattern in (_TITLE_EDITION_BRACKET_SUFFIX_RE, _TITLE_EDITION_DASH_SUFFIX_RE):
        cleaned = pattern.sub("", cleaned).strip(" -–—")
    return cleaned or str(title).strip()


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
    title_score = SequenceMatcher(
        None,
        _normalize(title),
        _normalize(recording.get("title", "")),
    ).ratio()
    artist_score = SequenceMatcher(
        None,
        _normalize(artist),
        _normalize(_artist_credit(recording)),
    ).ratio()
    api_score = max(0.0, min(1.0, float(recording.get("score", 0)) / 100.0))
    return round((title_score * 0.45) + (artist_score * 0.40) + (api_score * 0.15), 4)


def _date_key(value: str | None) -> tuple[int, int, int]:
    parts = str(value or "").split("-")
    try:
        return tuple(
            int(parts[index]) if index < len(parts) else 1 for index in range(3)
        )  # type: ignore[return-value]
    except ValueError:
        return (9999, 12, 31)


def _release_original_date(release: dict[str, Any]) -> str | None:
    """Prefer the release-group origin over a later reissue date."""
    release_group = (
        release.get("release-group")
        if isinstance(release.get("release-group"), dict)
        else {}
    )
    candidates = [
        str(value).strip()
        for value in (
            release_group.get("first-release-date"),
            release.get("date"),
        )
        if str(value or "").strip()
    ]
    return min(candidates, key=_date_key) if candidates else None


def _metadata_from_recording(
    recording: dict[str, Any],
    artist: str,
    title: str,
) -> TrackMetadata:
    score = _score_recording(recording, artist, title)
    releases = [
        release
        for release in recording.get("releases", [])
        if isinstance(release, dict)
    ]
    dated = [release for release in releases if _release_original_date(release)]
    earliest = (
        min(
            dated,
            key=lambda item: _date_key(_release_original_date(item)),
        )
        if dated
        else {}
    )
    release_group = (
        earliest.get("release-group")
        if isinstance(earliest.get("release-group"), dict)
        else {}
    )
    credits = (
        recording.get("artist-credit")
        if isinstance(recording.get("artist-credit"), list)
        else []
    )
    artist_entity = next(
        (
            item.get("artist")
            for item in credits
            if isinstance(item, dict) and isinstance(item.get("artist"), dict)
        ),
        {},
    )
    area = artist_entity.get("area") if isinstance(artist_entity.get("area"), dict) else {}
    begin_area = (
        artist_entity.get("begin-area")
        if isinstance(artist_entity.get("begin-area"), dict)
        else {}
    )
    release_date = _release_original_date(earliest) if earliest else None
    release_titles = list(
        dict.fromkeys(
            [
                str(release.get("title", "")).strip()
                for release in releases
                if str(release.get("title", "")).strip()
            ]
            + (
                [str(release_group.get("title", "")).strip()]
                if str(release_group.get("title", "")).strip()
                else []
            )
        )
    )
    return TrackMetadata(
        artist=artist,
        title=title,
        recording_mbid=str(recording.get("id", "")).strip() or None,
        artist_mbid=str(artist_entity.get("id", "")).strip() or None,
        release_group_mbid=str(release_group.get("id", "")).strip() or None,
        release_group_primary_type=str(release_group.get("primary-type") or "").strip() or None,
        release_group_secondary_types=tuple(
            str(item).strip()
            for item in (release_group.get("secondary-types") or [])
            if str(item).strip()
        ),
        isrcs=[str(value) for value in recording.get("isrcs", []) if str(value).strip()],
        original_release_date=release_date,
        original_release_year=(
            int(release_date[:4])
            if release_date and release_date[:4].isdigit()
            else None
        ),
        artist_country=str(artist_entity.get("country", "")).upper() or None,
        artist_area=str(area.get("name") or begin_area.get("name") or "").strip() or None,
        matched_artist=_artist_credit(recording) or None,
        release_titles=release_titles,
        match_score=score,
        confidence=(
            "high" if score >= HIGH_MATCH_SCORE else "medium" if score >= MIN_MATCH_SCORE else "low"
        ),
    )


def _select_best_metadata(
    candidates: list[TrackMetadata],
) -> TrackMetadata:
    """Use the earliest first release among confidently equivalent recordings.

    Reissues and remasters remain valid playback choices. This selection only
    normalizes the canonical first-release metadata used for hard constraints.
    """
    if not candidates:
        raise ValueError("No metadata candidates were provided")

    reliable_dated = [
        candidate
        for candidate in candidates
        if candidate.match_score >= MIN_MATCH_SCORE
        and candidate.original_release_date
    ]
    if reliable_dated:
        return min(
            reliable_dated,
            key=lambda candidate: (
                _date_key(candidate.original_release_date),
                -candidate.match_score,
            ),
        )
    return max(candidates, key=lambda candidate: candidate.match_score)


async def _rate_limited_get(
    client: httpx.AsyncClient,
    params: dict[str, str],
) -> httpx.Response:
    """Use the process-wide MusicBrainz request scheduler."""
    return await rate_limited_get(
        client,
        f"{API_ROOT}/recording",
        params=params,
    )


_ORIGINAL_RELEASE_TYPES = {"Album", "Single", "EP"}


def _is_confidently_original_release(metadata: TrackMetadata) -> bool:
    """Low-risk signal that the primary match is not a misleadingly-dated compilation.

    A clean Album/Single/EP release-group (no Compilation/Live/Remix/Demo/Broadcast/...
    secondary type) with a high title/artist match score is not absolute proof that no
    still-earlier release of the same nominal type exists (e.g. an earlier single later
    collected on an album, not surfaced by the primary bounded search) -- but it reliably
    excludes the scenario the historical probe was originally added for: a compilation/
    "best of"/live release whose date would otherwise misrepresent the true original
    release year. Empirically (see the live A/B check that motivated this gate), MusicBrainz
    frequently surfaces exactly a Live or Compilation release-group as the earliest-dated
    match even for well-known, unambiguous studio tracks -- the secondary-types check is
    what does most of the real protective work here, not the primary-type check.
    """
    return (
        metadata.match_score >= HIGH_MATCH_SCORE
        and metadata.release_group_primary_type in _ORIGINAL_RELEASE_TYPES
        and not metadata.release_group_secondary_types
    )


def _historical_probe_cutoff(
    metadata: TrackMetadata,
    constraints: MetadataConstraints,
) -> int | None:
    """Return the latest year needed to resolve an earlier first release.

    Skipped when the primary metadata is already a confidently-original album release
    exactly matching (or already inside) the requested year -- see
    _is_confidently_original_release for the accepted trade-off. Compilations, live albums,
    remixes and any lower-confidence or type-ambiguous match still always probe.
    """
    year = metadata.original_release_year
    if constraints.release_year is not None:
        if year == constraints.release_year and _is_confidently_original_release(metadata):
            return None
        return constraints.release_year
    if (
        constraints.release_year_from is not None
        and constraints.release_year_to is not None
    ):
        if (
            year is not None
            and constraints.release_year_from <= year <= constraints.release_year_to
            and _is_confidently_original_release(metadata)
        ):
            return None
        return constraints.release_year_to
    if constraints.release_year_from is not None:
        if year is None or year >= constraints.release_year_from:
            return constraints.release_year_from - 1
        return None
    if (
        constraints.release_year_to is not None
        and (year is None or year > constraints.release_year_to)
    ):
        return constraints.release_year_to
    return None


async def _lookup_historical_metadata(
    artist: str,
    title: str,
    cutoff_year: int,
    *,
    client: httpx.AsyncClient | None = None,
) -> TrackMetadata | None:
    """Find the earliest reliable recording released no later than cutoff."""
    owns_client = client is None
    active_client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(8.0),
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    try:
        query = (
            f'recording:"{title}" AND artist:"{artist}" AND '
            f'firstreleasedate:[* TO {cutoff_year}-12-31] AND status:official'
        )
        response = await _rate_limited_get(
            active_client,
            {
                "query": query,
                "fmt": "json",
                "limit": "100",
                "inc": "artists+releases+release-groups+isrcs",
            },
        )
        response.raise_for_status()
        recordings = [
            item
            for item in response.json().get("recordings", [])
            if isinstance(item, dict)
        ]
        if not recordings:
            return None
        metadata = _select_best_metadata(
            [
                _metadata_from_recording(item, artist, title)
                for item in recordings
            ]
        )
        return (
            metadata
            if metadata.match_score >= MIN_MATCH_SCORE
            else None
        )
    except (httpx.HTTPError, ValueError, TypeError):
        return None
    finally:
        if owns_client:
            await active_client.aclose()


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
            {
                "query": query,
                "fmt": "json",
                "limit": "20",
                "inc": "artists+releases+release-groups+isrcs",
            },
        )
        response.raise_for_status()
        candidates = [
            item
            for item in response.json().get("recordings", [])
            if isinstance(item, dict)
        ]
        if not candidates:
            metadata = TrackMetadata(
                artist=artist,
                title=title,
                warnings=["No MusicBrainz match"],
            )
            _write_cache(metadata, ttl=NEGATIVE_TTL_SECONDS, path=cache_path)
            return metadata
        metadata = _select_best_metadata(
            [
                _metadata_from_recording(item, artist, title)
                for item in candidates
            ]
        )
        if metadata.match_score < MIN_MATCH_SCORE:
            metadata.warnings.append("MusicBrainz match confidence is too low")
        _write_cache(metadata, ttl=_metadata_ttl(metadata), path=cache_path)
        return metadata
    except (httpx.HTTPError, ValueError, TypeError, sqlite3.Error) as error:
        return TrackMetadata(
            artist=artist,
            title=title,
            warnings=[f"Metadata lookup unavailable: {type(error).__name__}"],
        )
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


def _title_matches(actual: str, expected: str) -> bool:
    actual_norm = _normalize(actual)
    expected_norm = _normalize(expected)
    if not actual_norm or not expected_norm:
        return False
    return (
        actual_norm == expected_norm
        or SequenceMatcher(None, actual_norm, expected_norm).ratio() >= 0.95
    )


def _album_matches(actual: str, expected: str) -> bool:
    actual_norm = _normalize(actual)
    expected_norm = _normalize(expected)
    if not actual_norm or not expected_norm:
        return False
    if actual_norm == expected_norm:
        return True
    suffix = actual_norm[len(expected_norm) :].strip() if actual_norm.startswith(expected_norm) else ""
    edition_terms = {
        "remaster",
        "remastered",
        "deluxe",
        "edition",
        "expanded",
        "anniversary",
        "reissue",
    }
    return bool(suffix) and all(
        token.isdigit() or token in edition_terms for token in suffix.split()
    )


def _is_explicit_exception(
    metadata: TrackMetadata,
    constraints: MetadataConstraints,
) -> bool:
    actual_artist = metadata.matched_artist or metadata.artist
    return any(
        _artist_matches(actual_artist, exception["artist"])
        and _title_matches(metadata.title, exception["title"])
        for exception in constraints.exception_tracks
    )


def validate_metadata(
    metadata: TrackMetadata,
    constraints: MetadataConstraints,
) -> ValidationResult:
    if metadata.match_score >= MIN_MATCH_SCORE and _is_explicit_exception(metadata, constraints):
        return ValidationResult(status="valid", violations=[], metadata=metadata)

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
            violations.append(
                f"artist country {metadata.artist_country} does not match {constraints.artist_country}"
            )
    actual_artist = metadata.matched_artist or metadata.artist
    if constraints.allowed_artists:
        if not actual_artist:
            unknown = True
        elif not any(
            _artist_matches(actual_artist, expected)
            for expected in constraints.allowed_artists
        ):
            violations.append(f"artist {actual_artist} is not in allowed artists")
    if any(
        actual_artist and _artist_matches(actual_artist, excluded)
        for excluded in constraints.excluded_artists
    ):
        violations.append(f"artist {actual_artist} is excluded")
    if constraints.allowed_albums:
        if not metadata.release_titles:
            unknown = True
        elif not any(
            _album_matches(title, expected)
            for title in metadata.release_titles
            for expected in constraints.allowed_albums
        ):
            violations.append("track is not listed on an allowed album")
    for excluded in constraints.excluded_albums:
        if any(_album_matches(title, excluded) for title in metadata.release_titles):
            violations.append(f"track is listed on excluded album {excluded}")
            break
    status: ValidationStatus = "invalid" if violations else "unknown" if unknown else "valid"
    return ValidationResult(status=status, violations=violations, metadata=metadata)


async def _enrich_artist_origin(
    metadata: TrackMetadata,
    constraints: MetadataConstraints,
    *,
    client: httpx.AsyncClient | None = None,
    cache_path: Path | None = None,
) -> TrackMetadata:
    """Resolve missing artist origin only when a country hard constraint requires it."""
    if (
        constraints.artist_country is None
        or metadata.artist_country
        or not metadata.artist_mbid
        or metadata.match_score < MIN_MATCH_SCORE
    ):
        return metadata

    origin = await lookup_artist_origin(metadata.artist_mbid, client=client)
    if origin is None:
        return metadata

    metadata.artist_country = origin.country
    if not metadata.artist_area:
        metadata.artist_area = origin.area
    if origin.country or origin.area:
        with suppress(sqlite3.Error):
            _write_cache(metadata, ttl=_metadata_ttl(metadata), path=cache_path)
    return metadata


async def validate_candidate(
    candidate: dict[str, Any],
    constraints: MetadataConstraints,
    *,
    client: httpx.AsyncClient | None = None,
    cache_path: Path | None = None,
) -> ValidationResult:
    artist = str(candidate.get("artist", candidate.get("artists", ""))).strip()
    title = _strip_title_edition_suffix(str(candidate.get("title", "")).strip())
    metadata = await lookup_track_metadata(
        artist,
        title,
        client=client,
        cache_path=cache_path,
    )

    cutoff = _historical_probe_cutoff(metadata, constraints)
    if cutoff is not None:
        historical = await _lookup_historical_metadata(
            artist,
            title,
            cutoff,
            client=client,
        )
        if historical is not None and (
            metadata.original_release_date is None
            or _date_key(historical.original_release_date)
            < _date_key(metadata.original_release_date)
        ):
            metadata = historical
            with suppress(sqlite3.Error):
                _write_cache(metadata, ttl=_metadata_ttl(metadata), path=cache_path)

    metadata = await _enrich_artist_origin(
        metadata,
        constraints,
        client=client,
        cache_path=cache_path,
    )
    return validate_metadata(metadata, constraints)
