from __future__ import annotations

import asyncio

import pytest

from backend import playlist_ordering as ordering
from backend.metadata_validation import TrackMetadata, ValidationResult
from backend.reccobeats_features import ReccoBeatsAudioEvidence


def _track(title: str, artist: str) -> dict:
    return {
        "title": title,
        "artists": artist,
        "video_id": f"{artist}-{title}",
    }


def _metadata(
    artist: str,
    title: str,
    *,
    year: int | None,
    score: float = 0.99,
) -> TrackMetadata:
    return TrackMetadata(
        artist=artist,
        title=title,
        original_release_date=f"{year}-01-01" if year is not None else None,
        original_release_year=year,
        match_score=score,
        confidence="high" if score >= 0.90 else "low",
    )


def test_structured_chronological_order_requires_trusted_confidence() -> None:
    oldest = {
        "chronological_order": "oldest_first",
        "field_confidence": {"chronological_order": 0.99},
    }
    newest = {
        "chronological_order": "newest_first",
        "field_confidence": {"chronological_order": 0.96},
    }
    uncertain = {
        "chronological_order": "oldest_first",
        "field_confidence": {"chronological_order": 0.40},
        "confidence": "medium",
    }

    assert ordering.chronological_order_from_payload(oldest) == "oldest_first"
    assert ordering.chronological_order_from_payload(newest) == "newest_first"
    assert ordering.chronological_order_from_payload(uncertain) is None


def test_local_fallback_recognizes_common_chronological_requests() -> None:
    assert (
        ordering.chronological_order_from_payload(
            None,
            "Riordina le canzoni dalla più vecchia alla più recente",
        )
        == "oldest_first"
    )
    assert (
        ordering.chronological_order_from_payload(
            None,
            "Ordinale dalla più recente alla più vecchia",
        )
        == "newest_first"
    )
    assert (
        ordering.chronological_order_from_payload(
            None,
            "Make the playlist grow gradually in energy toward the end",
        )
        is None
    )


def test_release_year_ordering_uses_original_release_metadata(monkeypatch) -> None:
    tracks = [
        _track("Middle", "Artist B"),
        _track("Newest", "Artist C"),
        _track("Oldest", "Artist A"),
    ]
    years = {
        ("Artist A", "Oldest"): 1975,
        ("Artist B", "Middle"): 1990,
        ("Artist C", "Newest"): 2001,
    }

    async def fake_lookup(artist: str, title: str, **kwargs) -> TrackMetadata:
        del kwargs
        return _metadata(artist, title, year=years[(artist, title)])

    monkeypatch.setattr(ordering, "lookup_track_metadata", fake_lookup)

    oldest_first = asyncio.run(
        ordering.order_tracks_by_release_date(tracks, "oldest_first")
    )
    newest_first = asyncio.run(
        ordering.order_tracks_by_release_date(tracks, "newest_first")
    )

    assert [track["title"] for track in oldest_first] == [
        "Oldest",
        "Middle",
        "Newest",
    ]
    assert [track["title"] for track in newest_first] == [
        "Newest",
        "Middle",
        "Oldest",
    ]


def test_embedded_verified_metadata_avoids_lookup(monkeypatch) -> None:
    tracks = [
        {
            **_track("Later", "Artist B"),
            "metadata_validation": {
                "original_release_date": "1999-02-01",
                "original_release_year": 1999,
                "match_score": 0.97,
                "confidence": "high",
            },
        },
        {
            **_track("Earlier", "Artist A"),
            "metadata_validation": {
                "original_release_date": "1982-06-01",
                "original_release_year": 1982,
                "match_score": 0.96,
                "confidence": "high",
            },
        },
    ]

    async def unexpected_lookup(*args, **kwargs):
        raise AssertionError("embedded verified metadata should avoid a lookup")

    monkeypatch.setattr(ordering, "lookup_track_metadata", unexpected_lookup)

    result = asyncio.run(ordering.order_tracks_by_release_date(tracks, "oldest_first"))
    assert [track["title"] for track in result] == ["Earlier", "Later"]


def test_live_version_always_uses_underlying_song_original_year(monkeypatch) -> None:
    tracks = [
        {
            **_track("Other Song", "Other Artist"),
            "metadata_validation": {
                "original_release_date": "2010-01-01",
                "original_release_year": 2010,
                "match_score": 0.98,
                "confidence": "high",
            },
        },
        {
            **_track("Eccoti (Live)", "Max Pezzali"),
            "album": "Live Tour 2015",
            "metadata_validation": {
                "original_release_date": "2015-05-01",
                "original_release_year": 2015,
                "match_score": 0.99,
                "confidence": "high",
            },
        },
    ]
    lookups: list[tuple[str, str]] = []

    async def fake_lookup(artist: str, title: str, **kwargs) -> TrackMetadata:
        del kwargs
        lookups.append((artist, title))
        assert (artist, title) == ("Max Pezzali", "Eccoti")
        return _metadata(artist, title, year=2005)

    monkeypatch.setattr(ordering, "lookup_track_metadata", fake_lookup)

    result = asyncio.run(ordering.order_tracks_by_release_date(tracks, "oldest_first"))

    assert lookups == [("Max Pezzali", "Eccoti")]
    assert [track["title"] for track in result] == ["Eccoti (Live)", "Other Song"]
    assert result[0]["video_id"] == "Max Pezzali-Eccoti (Live)"


def test_live_album_marker_uses_original_song_even_without_live_in_title(monkeypatch) -> None:
    tracks = [
        {**_track("Song", "Artist"), "album": "Artist Live at Home"},
        {
            **_track("Later", "Artist B"),
            "metadata_validation": {
                "original_release_year": 2000,
                "match_score": 0.99,
                "confidence": "high",
            },
        },
    ]

    async def fake_lookup(artist: str, title: str, **kwargs) -> TrackMetadata:
        del kwargs
        assert (artist, title) == ("Artist", "Song")
        return _metadata(artist, title, year=1980)

    monkeypatch.setattr(ordering, "lookup_track_metadata", fake_lookup)

    result = asyncio.run(ordering.order_tracks_by_release_date(tracks, "oldest_first"))
    assert [track["title"] for track in result] == ["Song", "Later"]


def test_remaster_compares_exact_and_versionless_years(monkeypatch) -> None:
    tracks = [
        _track("Original Song (2011 Remastered)", "Artist"),
        {
            **_track("Middle Song", "Other"),
            "metadata_validation": {
                "original_release_year": 1990,
                "match_score": 0.99,
                "confidence": "high",
            },
        },
    ]
    lookups: list[str] = []

    async def fake_lookup(artist: str, title: str, **kwargs) -> TrackMetadata:
        del kwargs
        lookups.append(title)
        year = 2011 if "Remastered" in title else 1978
        return _metadata(artist, title, year=year)

    monkeypatch.setattr(ordering, "lookup_track_metadata", fake_lookup)

    result = asyncio.run(ordering.order_tracks_by_release_date(tracks, "oldest_first"))

    assert lookups == ["Original Song (2011 Remastered)", "Original Song"]
    assert [track["title"] for track in result] == [
        "Original Song (2011 Remastered)",
        "Middle Song",
    ]


def test_weak_exact_match_uses_historical_fallback(monkeypatch) -> None:
    tracks = [
        _track("Known Song", "Artist"),
        {
            **_track("Later", "Other"),
            "metadata_validation": {
                "original_release_year": 2002,
                "match_score": 0.99,
                "confidence": "high",
            },
        },
    ]
    fallback_calls: list[tuple[str, str]] = []

    async def weak_lookup(artist: str, title: str, **kwargs) -> TrackMetadata:
        del kwargs
        return _metadata(artist, title, year=None, score=0.20)

    async def fake_validate(candidate, constraints, **kwargs) -> ValidationResult:
        del constraints, kwargs
        fallback_calls.append((candidate["artist"], candidate["title"]))
        metadata = _metadata(candidate["artist"], candidate["title"], year=1984)
        return ValidationResult(status="valid", violations=[], metadata=metadata)

    monkeypatch.setattr(ordering, "lookup_track_metadata", weak_lookup)
    monkeypatch.setattr(ordering, "validate_candidate", fake_validate)

    result = asyncio.run(ordering.order_tracks_by_release_date(tracks, "oldest_first"))

    assert fallback_calls == [("Artist", "Known Song")]
    assert [track["title"] for track in result] == ["Known Song", "Later"]


def test_year_only_metadata_is_sufficient_and_equal_years_keep_relative_order(monkeypatch) -> None:
    tracks = [
        _track("Same Year A", "Artist A"),
        _track("Newer", "Artist C"),
        _track("Same Year B", "Artist B"),
    ]
    years = {
        "Same Year A": 1995,
        "Same Year B": 1995,
        "Newer": 2000,
    }

    async def fake_lookup(artist: str, title: str, **kwargs) -> TrackMetadata:
        del kwargs
        return TrackMetadata(
            artist=artist,
            title=title,
            original_release_year=years[title],
            original_release_date=None,
            match_score=0.99,
            confidence="high",
        )

    monkeypatch.setattr(ordering, "lookup_track_metadata", fake_lookup)

    oldest = asyncio.run(ordering.order_tracks_by_release_date(tracks, "oldest_first"))
    newest = asyncio.run(ordering.order_tracks_by_release_date(tracks, "newest_first"))

    assert [track["title"] for track in oldest] == [
        "Same Year A",
        "Same Year B",
        "Newer",
    ]
    assert [track["title"] for track in newest] == [
        "Newer",
        "Same Year A",
        "Same Year B",
    ]


def test_explicit_chronology_fails_only_after_fallback_is_exhausted(monkeypatch) -> None:
    tracks = [_track("Known", "Artist A"), _track("Unknown", "Artist B")]
    fallback_titles: list[str] = []

    async def fake_lookup(artist: str, title: str, **kwargs) -> TrackMetadata:
        del kwargs
        if title == "Known":
            return _metadata(artist, title, year=1988)
        return _metadata(artist, title, year=None, score=0.20)

    async def fake_validate(candidate, constraints, **kwargs) -> ValidationResult:
        del constraints, kwargs
        fallback_titles.append(candidate["title"])
        metadata = _metadata(
            candidate["artist"],
            candidate["title"],
            year=None,
            score=0.20,
        )
        return ValidationResult(status="unknown", violations=[], metadata=metadata)

    monkeypatch.setattr(ordering, "lookup_track_metadata", fake_lookup)
    monkeypatch.setattr(ordering, "validate_candidate", fake_validate)

    with pytest.raises(ValueError, match="could not verify the original release year"):
        asyncio.run(ordering.order_tracks_by_release_date(tracks, "oldest_first"))

    assert fallback_titles == ["Unknown"]


def test_strip_version_suffix_recognizes_classic_and_extended_editions() -> None:
    assert ordering._strip_version_suffix("Song (Classic Version)") == "Song"
    assert ordering._strip_version_suffix("Song (Extended Version)") == "Song"
    assert ordering._strip_version_suffix("Song (Anniversary Version)") == "Song"
    assert ordering._strip_version_suffix("Song (Deluxe Version)") == "Song"
    # Already-covered terms must keep working after widening the pattern.
    assert ordering._strip_version_suffix("Song (Remastered)") == "Song"
    assert ordering._strip_version_suffix("Take on Me") == "Take on Me"


def test_structured_energy_order_requires_trusted_confidence() -> None:
    increasing = {
        "energy_order": "increasing",
        "field_confidence": {"energy_order": 0.95},
    }
    uncertain = {
        "energy_order": "decreasing",
        "field_confidence": {"energy_order": 0.30},
        "confidence": "medium",
    }

    assert ordering.energy_order_from_payload(increasing) == "increasing"
    assert ordering.energy_order_from_payload(uncertain) is None


def test_local_fallback_recognizes_common_energy_requests() -> None:
    assert (
        ordering.energy_order_from_payload(None, "Rock playlist with increasing energy")
        == "increasing"
    )
    assert (
        ordering.energy_order_from_payload(None, "Playlist rock con energia decrescente")
        == "decreasing"
    )
    assert (
        ordering.energy_order_from_payload(None, "Keep the energy steady throughout")
        == "steady"
    )
    assert ordering.energy_order_from_payload(None, "A relaxing jazz playlist") is None


def test_local_fallback_recognizes_energy_requests_in_french_spanish_german() -> None:
    """Standing project requirement: prompt interpretation must cover English, Italian,
    French, Spanish and German, not just the first two."""
    assert (
        ordering.energy_order_from_payload(None, "Playlist rock avec une énergie croissante")
        == "increasing"
    )
    assert (
        ordering.energy_order_from_payload(None, "Playlist avec une énergie décroissante")
        == "decreasing"
    )
    assert (
        ordering.energy_order_from_payload(None, "Playlist avec une énergie constante")
        == "steady"
    )
    assert (
        ordering.energy_order_from_payload(None, "Playlist con energía creciente")
        == "increasing"
    )
    assert (
        ordering.energy_order_from_payload(None, "Playlist con energía decreciente")
        == "decreasing"
    )
    assert (
        ordering.energy_order_from_payload(None, "Playlist con energía constante")
        == "steady"
    )
    assert (
        ordering.energy_order_from_payload(None, "Playlist mit steigender Energie")
        == "increasing"
    )
    assert (
        ordering.energy_order_from_payload(None, "Playlist mit abnehmender Energie")
        == "decreasing"
    )
    assert (
        ordering.energy_order_from_payload(None, "Playlist mit konstanter Energie")
        == "steady"
    )


def test_local_fallback_does_not_false_positive_on_loose_steady_wording() -> None:
    """Regression test for final whole-branch review Finding 1.

    A bare "even" or "consistent" anywhere near the word "energy" used to be
    misdetected as a request for steady energy, even when the prompt clearly meant
    something else (or explicitly asked for a direction other than steady).
    """
    assert (
        ordering.energy_order_from_payload(
            None,
            "High energy party tracks, even the slow ones should hit hard",
        )
        is None
    )
    assert (
        ordering.energy_order_from_payload(
            None,
            "Workout playlist, keep the energy building even higher toward the end",
        )
        == "increasing"
    )
    assert (
        ordering.energy_order_from_payload(
            None,
            "Even in the low-energy moments keep it interesting",
        )
        is None
    )
    assert (
        ordering.energy_order_from_payload(
            None,
            "Energy building throughout, no consistent lulls",
        )
        == "increasing"
    )


def _evidence(energy: float | None) -> ReccoBeatsAudioEvidence:
    if energy is None:
        return ReccoBeatsAudioEvidence()
    return ReccoBeatsAudioEvidence(energy=energy)


def test_energy_ordering_sorts_matched_tracks_increasing_and_decreasing(monkeypatch) -> None:
    tracks = [_track("Loud", "A"), _track("Quiet", "B"), _track("Medium", "C")]
    energies = {"Loud": 0.9, "Quiet": 0.1, "Medium": 0.5}

    async def fake_evidence(artist: str, title: str, **kwargs) -> ReccoBeatsAudioEvidence:
        del artist, kwargs
        return _evidence(energies[title])

    monkeypatch.setattr(ordering, "audio_evidence_for_track", fake_evidence)

    increasing = asyncio.run(ordering.order_tracks_by_energy(tracks, "increasing"))
    decreasing = asyncio.run(ordering.order_tracks_by_energy(tracks, "decreasing"))

    assert [track["title"] for track in increasing] == ["Quiet", "Medium", "Loud"]
    assert [track["title"] for track in decreasing] == ["Loud", "Medium", "Quiet"]


def test_energy_ordering_keeps_unmatched_tracks_in_original_position(monkeypatch) -> None:
    tracks = [_track("Loud", "A"), _track("Unknown", "B"), _track("Quiet", "C")]
    energies = {"Loud": 0.9, "Quiet": 0.1}

    async def fake_evidence(artist: str, title: str, **kwargs) -> ReccoBeatsAudioEvidence:
        del artist, kwargs
        return _evidence(energies.get(title))

    monkeypatch.setattr(ordering, "audio_evidence_for_track", fake_evidence)

    result = asyncio.run(ordering.order_tracks_by_energy(tracks, "increasing"))

    # "Unknown" has no ReccoBeats evidence and must keep its original slot (index 1);
    # the matched tracks reorder around it.
    assert [track["title"] for track in result] == ["Quiet", "Unknown", "Loud"]


def test_energy_ordering_steady_chains_by_nearest_energy(monkeypatch) -> None:
    tracks = [_track("A", "X"), _track("B", "X"), _track("C", "X"), _track("D", "X")]
    energies = {"A": 0.10, "B": 0.30, "C": 0.50, "D": 0.90}

    async def fake_evidence(artist: str, title: str, **kwargs) -> ReccoBeatsAudioEvidence:
        del artist, kwargs
        return _evidence(energies[title])

    async def fake_tags(tracks):
        return [ordering.LastfmTagEvidence() for _ in tracks]

    monkeypatch.setattr(ordering, "audio_evidence_for_track", fake_evidence)
    monkeypatch.setattr(ordering, "tag_evidence_for_tracks", fake_tags)

    result = asyncio.run(ordering.order_tracks_by_energy(tracks, "steady"))

    # Chain starts at the median (C, index 2 of the 4 energy-sorted tracks), then always
    # steps to the nearest remaining energy: C(0.50) -> B(0.30) -> A(0.10) -> D(0.90).
    # No tag evidence here, so the genre gate is a no-op (fail-open) -- pure energy chaining.
    assert [track["title"] for track in result] == ["C", "B", "A", "D"]


def test_energy_ordering_returns_tracks_unchanged_without_direction() -> None:
    tracks = [_track("A", "X"), _track("B", "Y")]
    result = asyncio.run(ordering.order_tracks_by_energy(tracks, None))
    assert result == tracks


def test_energy_ordering_applies_chronological_order_within_energy_bands(monkeypatch) -> None:
    tracks = [
        _track("T1", "Artist"),
        _track("T2", "Artist"),
        _track("T3", "Artist"),
        _track("T4", "Artist"),
        _track("T5", "Artist"),
        _track("T6", "Artist"),
    ]
    # Ranked by energy: T1 < T2 < T3 < T4 < T5 < T6 -> bands of 2: [T1,T2] [T3,T4] [T5,T6]
    energies = {"T1": 0.10, "T2": 0.15, "T3": 0.40, "T4": 0.45, "T5": 0.80, "T6": 0.85}
    years = {"T1": 2000, "T2": 1990, "T3": 2010, "T4": 1980, "T6": 1970}  # T5 unresolvable

    async def fake_evidence(artist: str, title: str, **kwargs) -> ReccoBeatsAudioEvidence:
        del artist, kwargs
        return _evidence(energies[title])

    async def fake_lookup(artist: str, title: str, **kwargs) -> TrackMetadata:
        del kwargs
        year = years.get(title)
        return _metadata(artist, title, year=year, score=0.99 if year is not None else 0.20)

    async def fake_validate(candidate, constraints, **kwargs) -> ValidationResult:
        del constraints, kwargs
        metadata = _metadata(candidate["artist"], candidate["title"], year=None, score=0.20)
        return ValidationResult(status="unknown", violations=[], metadata=metadata)

    monkeypatch.setattr(ordering, "audio_evidence_for_track", fake_evidence)
    monkeypatch.setattr(ordering, "lookup_track_metadata", fake_lookup)
    monkeypatch.setattr(ordering, "validate_candidate", fake_validate)

    result = asyncio.run(
        ordering.order_tracks_by_energy(
            tracks,
            "increasing",
            chronological_direction="oldest_first",
        )
    )

    # Band order follows energy (ascending). Within each band, oldest_first sorts by year;
    # T5 has no resolvable year and keeps its slot ahead of T6 in its band.
    assert [track["title"] for track in result] == ["T2", "T1", "T4", "T3", "T5", "T6"]


def test_energy_ordering_steady_ignores_chronological_direction(monkeypatch) -> None:
    tracks = [_track("A", "X"), _track("B", "X"), _track("C", "X")]
    energies = {"A": 0.1, "B": 0.5, "C": 0.9}

    async def fake_evidence(artist: str, title: str, **kwargs) -> ReccoBeatsAudioEvidence:
        del artist, kwargs
        return _evidence(energies[title])

    async def unexpected_lookup(*args, **kwargs):
        raise AssertionError("steady must never trigger a chronological lookup")

    async def fake_tags(tracks):
        return [ordering.LastfmTagEvidence() for _ in tracks]

    monkeypatch.setattr(ordering, "audio_evidence_for_track", fake_evidence)
    monkeypatch.setattr(ordering, "lookup_track_metadata", unexpected_lookup)
    monkeypatch.setattr(ordering, "tag_evidence_for_tracks", fake_tags)

    result = asyncio.run(
        ordering.order_tracks_by_energy(
            tracks,
            "steady",
            chronological_direction="oldest_first",
        )
    )
    assert [track["title"] for track in result] == ["B", "A", "C"]


def test_chained_by_energy_without_tags_crosses_genre_boundary_every_step() -> None:
    """Baseline for the gated test below: confirms the ungated chain really does
    cross the genre boundary on every step for this fixture, so the gated test's
    improvement claim is checked against a verified starting point."""
    tracks = [_track("A", "W"), _track("B", "X"), _track("C", "Y"), _track("D", "Z")]
    energies = [0.50, 0.51, 0.90, 0.89]

    result = ordering._chained_by_energy(tracks, energies)

    assert [track["title"] for track in result] == ["D", "C", "B", "A"]


def test_energy_ordering_steady_gates_by_tag_compatibility_when_available(
    monkeypatch,
) -> None:
    """Two tracks can have near-identical energy while being unrelated in genre,
    so "steady energy" chaining by energy alone can place them adjacent by
    accident.

    Four tracks, two genre clusters of two (rock: A/C: energy .50/.90; kpop: B/D:
    energy .51/.89) deliberately interleaved by energy so a pure energy-nearest
    chain crosses the genre boundary on every single step. With only two clusters
    of two, a chain touching both must cross the boundary at least once -- the tag
    gate cannot eliminate that, but it should minimize it to exactly that one
    unavoidable crossing instead of crossing back and forth.
    """
    tracks = [_track("A", "W"), _track("B", "X"), _track("C", "Y"), _track("D", "Z")]
    energies = {"A": 0.50, "B": 0.51, "C": 0.90, "D": 0.89}
    tags_by_title = {
        "A": _tags("rock"),
        "B": _tags("kpop"),
        "C": _tags("rock"),
        "D": _tags("kpop"),
    }

    async def fake_evidence(artist: str, title: str, **kwargs) -> ReccoBeatsAudioEvidence:
        del artist, kwargs
        return _evidence(energies[title])

    async def fake_tags(tracks):
        return [tags_by_title[t["title"]] for t in tracks]

    monkeypatch.setattr(ordering, "audio_evidence_for_track", fake_evidence)
    monkeypatch.setattr(ordering, "tag_evidence_for_tracks", fake_tags)

    result = asyncio.run(ordering.order_tracks_by_energy(tracks, "steady"))

    # Without the gate this chains as D-C-B-A (three genre-mismatched boundaries:
    # kpop|rock, rock|kpop, kpop|rock -- verified directly against
    # _chained_by_energy with no tags argument). With the gate: D-B-A-C, crossing
    # the genre boundary exactly once (B->A), the unavoidable minimum for two
    # clusters of two tracks each.
    assert [track["title"] for track in result] == ["D", "B", "A", "C"]


def test_tag_compatible_is_fail_open_on_missing_evidence() -> None:
    populated = ordering.LastfmTagEvidence(track_tags=("Rock",))
    empty = ordering.LastfmTagEvidence()
    assert ordering._tag_compatible(populated, empty) is True
    assert ordering._tag_compatible(empty, populated) is True
    assert ordering._tag_compatible(empty, empty) is True


def test_tag_compatible_requires_shared_tag_when_both_populated() -> None:
    rock = ordering.LastfmTagEvidence(track_tags=("Rock", "Alt-Rock"))
    kpop = ordering.LastfmTagEvidence(track_tags=("K-Pop",))
    shared = ordering.LastfmTagEvidence(track_tags=("rock", "dance"))
    assert ordering._tag_compatible(rock, kpop) is False
    assert ordering._tag_compatible(rock, shared) is True


def _tags(*values: str) -> "ordering.LastfmTagEvidence":
    return ordering.LastfmTagEvidence(track_tags=values)


def _audio(**dimensions: float) -> ReccoBeatsAudioEvidence:
    return ReccoBeatsAudioEvidence(**dimensions)

