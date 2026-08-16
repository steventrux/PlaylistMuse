from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import backend.youtube as youtube
from backend import generation_runtime as runtime
from backend.metadata_validation import (
    MetadataConstraints,
    TrackMetadata,
    ValidationResult,
)
from backend.policy_enforcement import _ACTIVE_POLICY, _REPLACEMENT_MODE


class _SearchClient:
    def __init__(self, results):
        self.results = results

    def search(self, query, filter=None, limit=None):
        return list(self.results)


def test_title_matching_is_case_insensitive() -> None:
    assert youtube._title_score("90min", "90MIN") == 100.0
    assert youtube._title_score("Italodisco", "ITALODISCO") == 100.0


def test_variant_markers_only_reject_catalogue_additions() -> None:
    assert youtube._exclusion_reason(
        "Karaoke",
        album="Karaoke",
        artists="Boomdabash, Alessandra Amoroso",
        candidate_title="Karaoke",
        candidate_artists="Boomdabash",
        live=True,
        covers=True,
        remixes=True,
    ) is None
    assert youtube._exclusion_reason(
        "Karaoke (Live)",
        artists="Boomdabash",
        candidate_title="Karaoke",
        candidate_artists="Boomdabash",
        live=True,
        covers=True,
        remixes=True,
    ) == "excluded_live"
    assert youtube._exclusion_reason(
        "Karaoke (Cover)",
        artists="Boomdabash",
        candidate_title="Karaoke",
        candidate_artists="Boomdabash",
        live=True,
        covers=True,
        remixes=True,
    ) == "excluded_cover"


def test_resolver_accepts_song_whose_real_title_is_karaoke(monkeypatch) -> None:
    monkeypatch.setattr(
        youtube,
        "_read_youtube_cache_entry",
        lambda *args, **kwargs: (False, None, None),
    )
    monkeypatch.setattr(youtube, "_write_youtube_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        youtube,
        "_thread_client",
        lambda: _SearchClient(
            [
                {
                    "videoId": "karaoke-1",
                    "title": "Karaoke",
                    "artists": [
                        {"name": "Boomdabash"},
                        {"name": "Alessandra Amoroso"},
                    ],
                    "album": {"name": "Don’t Worry (Best of 2005-2020)"},
                }
            ]
        ),
    )

    track, diagnostic = youtube._resolve_one_with_diagnostic(
        {"artist": "Boomdabash", "title": "Karaoke"},
        {
            "exclude_live": True,
            "exclude_covers": True,
            "exclude_remixes": True,
        },
    )

    assert diagnostic is None
    assert track is not None
    assert track["title"] == "Karaoke"
    assert track["match_score"] == 100.0


def test_incremental_metadata_target_is_limited_to_simple_replenishment() -> None:
    requested_token = runtime._REQUESTED_SESSION_COUNT.set(25)
    resolved_token = runtime._RESOLVED_SESSION_TRACKS.set(
        tuple({"title": f"Track {index}"} for index in range(16))
    )
    quota_token = runtime._ACTIVE_RESOLUTION_QUOTAS.set(())
    exact_token = runtime._ACTIVE_EXACT_ARTIST_QUOTAS.set(())
    policy_token = _ACTIVE_POLICY.set(None)
    replacement_token = _REPLACEMENT_MODE.set(False)
    try:
        assert youtube._incremental_metadata_target(27) == 12
        runtime._ACTIVE_RESOLUTION_QUOTAS.set((SimpleNamespace(artist="Artist"),))
        assert youtube._incremental_metadata_target(27) is None
    finally:
        _REPLACEMENT_MODE.reset(replacement_token)
        _ACTIVE_POLICY.reset(policy_token)
        runtime._ACTIVE_EXACT_ARTIST_QUOTAS.reset(exact_token)
        runtime._ACTIVE_RESOLUTION_QUOTAS.reset(quota_token)
        runtime._RESOLVED_SESSION_TRACKS.reset(resolved_token)
        runtime._REQUESTED_SESSION_COUNT.reset(requested_token)


def test_metadata_filter_never_skips_validate_candidate_via_a_stale_cache(
    monkeypatch,
) -> None:
    """Regression test for a real bug (fixed 2026-08-15): `evaluate()` used to have its
    own `_read_cache`/`validate_metadata` fast path that bypassed `validate_candidate()`
    entirely on a cache hit -- including its per-request decision on whether a historical
    probe or artist-origin enrichment is still needed for constraints active in *this*
    request. Since the cache key is artist+title only (shared across all requests for up
    to 90 days), that fast path could silently starve a later, differently-constrained
    request of enrichment it needed. `_metadata_filter` must always route every candidate
    through `validate_candidate()`, with no shortcut in between."""
    constraints = MetadataConstraints(artist_country="IT")
    monkeypatch.setattr(youtube, "active_constraints", lambda: constraints)
    monkeypatch.setattr(youtube, "metadata_lookup_limit", lambda count: count)

    calls: list[str] = []

    async def fake_validate(candidate, active, client=None):
        calls.append(candidate["title"])
        return ValidationResult(
            status="valid",
            violations=[],
            metadata=TrackMetadata(
                artist=candidate["artist"],
                title=candidate["title"],
                matched_artist=candidate["artist"],
                artist_country="IT",
                match_score=0.98,
                confidence="high",
            ),
        )

    monkeypatch.setattr(youtube, "validate_candidate", fake_validate)

    candidate = {"artist": "Artist A", "title": "Track A"}
    asyncio.run(youtube._metadata_filter([candidate]))
    asyncio.run(youtube._metadata_filter([candidate]))

    assert calls == ["Track A", "Track A"]


def test_metadata_filter_dispatches_in_concurrent_batches(monkeypatch) -> None:
    """The MusicBrainz pacer is a single process-wide scheduler, so wall time should
    scale with the number of batches, not the number of candidates -- confirms candidates
    within a batch actually run concurrently rather than one at a time."""
    constraints = MetadataConstraints(release_year_from=2000, release_year_to=2026)
    monkeypatch.setattr(youtube, "active_constraints", lambda: constraints)
    monkeypatch.setattr(youtube, "metadata_lookup_limit", lambda count: count)
    monkeypatch.setattr(youtube, "METADATA_VALIDATION_BATCH_SIZE", 4)

    async def fake_validate(candidate, active, client=None):
        await asyncio.sleep(0.05)
        return ValidationResult(
            status="valid",
            violations=[],
            metadata=TrackMetadata(
                artist=candidate["artist"],
                title=candidate["title"],
                matched_artist=candidate["artist"],
                original_release_year=2024,
                match_score=0.98,
                confidence="high",
            ),
        )

    monkeypatch.setattr(youtube, "validate_candidate", fake_validate)
    candidates = [
        {"artist": f"Artist {index}", "title": f"Track {index}"} for index in range(8)
    ]

    start = time.perf_counter()
    accepted, rejected = asyncio.run(youtube._metadata_filter(candidates))
    elapsed = time.perf_counter() - start

    assert len(accepted) == 8
    assert not rejected
    # 8 candidates / batch size 4 = 2 batches * 0.05s each, not 8 * 0.05s sequential.
    # Generous margin for sandbox scheduling jitter.
    assert elapsed < 0.3


def test_metadata_filter_stops_after_verified_replenishment_reserve(monkeypatch) -> None:
    calls: list[str] = []
    constraints = MetadataConstraints(release_year_from=2000, release_year_to=2026)

    monkeypatch.setattr(youtube, "active_constraints", lambda: constraints)
    monkeypatch.setattr(youtube, "metadata_lookup_limit", lambda count: count)

    async def fake_validate(candidate, active, client=None):
        assert active is constraints
        calls.append(candidate["title"])
        return ValidationResult(
            status="valid",
            violations=[],
            metadata=TrackMetadata(
                artist=candidate["artist"],
                title=candidate["title"],
                matched_artist=candidate["artist"],
                original_release_year=2024,
                match_score=0.98,
                confidence="high",
            ),
        )

    monkeypatch.setattr(youtube, "validate_candidate", fake_validate)
    candidates = [
        {"artist": f"Artist {index}", "title": f"Track {index}"}
        for index in range(8)
    ]

    accepted, rejected = asyncio.run(
        youtube._metadata_filter(candidates, max_valid=3)
    )

    # Candidates are now dispatched in small concurrent batches
    # (METADATA_VALIDATION_BATCH_SIZE=4) rather than one at a time, so the max_valid
    # early-stop is only checked *between* batches: the first batch (0-3) all succeed
    # before the check ever sees len(accepted)>=3, so it can overshoot by up to one
    # batch's worth -- accepted lands on 4, not exactly 3, and the second batch (4-7)
    # is deferred in full.
    assert len(accepted) == 4
    assert calls == ["Track 0", "Track 1", "Track 2", "Track 3"]
    assert len(rejected) == 4
    assert all(
        item["unresolved_reason"] == "metadata_deferred_after_target"
        for item in rejected
    )
