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
    """Same audio-only genre-incoherence risk documented for the journey feature
    (docs/superpowers/specs/2026-08-26-journey-proximity-ordering-design.md): two
    tracks can have near-identical energy while being unrelated in genre, so
    "steady energy" chaining by energy alone can place them adjacent by accident.

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


def test_tag_closeness_counts_normalized_shared_tags() -> None:
    end = ordering.LastfmTagEvidence(track_tags=("Rock", "Alt-Rock", "90s"))
    close = ordering.LastfmTagEvidence(track_tags=("rock", "alt rock"))
    far = ordering.LastfmTagEvidence(track_tags=("jazz",))
    assert ordering._tag_closeness(close, end) == 2
    assert ordering._tag_closeness(far, end) == 0
    assert ordering._tag_closeness(ordering.LastfmTagEvidence(), end) is None
    assert ordering._tag_closeness(close, ordering.LastfmTagEvidence()) is None


def test_audio_distance_uses_shared_dimensions_only() -> None:
    a = ordering.ReccoBeatsAudioEvidence(energy=0.9, valence=0.5)
    b = ordering.ReccoBeatsAudioEvidence(energy=0.1, valence=0.5)
    assert ordering._audio_distance(a, b) == pytest.approx(0.5657, rel=1e-3)
    assert ordering._audio_distance(a, ordering.ReccoBeatsAudioEvidence()) is None


def _tags(*values: str) -> "ordering.LastfmTagEvidence":
    return ordering.LastfmTagEvidence(track_tags=values)


def _audio(**dimensions: float) -> ReccoBeatsAudioEvidence:
    return ReccoBeatsAudioEvidence(**dimensions)


def test_journey_proximity_ordering_noop_with_fewer_than_two_middle_tracks(monkeypatch) -> None:
    async def unexpected_tags(tracks):
        raise AssertionError("must not fetch evidence when there is nothing to reorder")

    monkeypatch.setattr(ordering, "tag_evidence_for_tracks", unexpected_tags)

    start = _track("Start", "A")
    end = _track("End", "B")
    result = asyncio.run(ordering.order_journey_tracks_by_proximity(start, [], end))
    assert result == []

    one = [_track("Mid", "C")]
    result_one = asyncio.run(ordering.order_journey_tracks_by_proximity(start, one, end))
    assert result_one == one


def test_greedy_journey_chain_alone_strands_a_start_like_track_at_the_end() -> None:
    """Baseline for the consensus test below: proves the forward-only walk really
    does mis-place "NearStart" (see that test's docstring for the full scenario),
    so the consensus test's improvement claim is checked against a verified
    starting point, not an assumed one."""
    start_tags, end_tags = _tags("rock", "pop"), _tags("metal", "doom")
    near_start_tags = _tags("rock", "pop")
    bridge_tags = _tags("rock", "metal")
    near_end_tags = _tags("metal", "doom")
    start_audio = _audio(energy=0.5)
    near_start_audio = _audio(energy=0.9)
    bridge_audio = _audio(energy=0.5)
    near_end_audio = _audio(energy=0.9)

    middle_tags = [near_start_tags, bridge_tags, near_end_tags]
    middle_audio = [near_start_audio, bridge_audio, near_end_audio]
    matched_indices = [0, 1, 2]
    closeness_to_end = {
        index: ordering._tag_closeness(middle_tags[index], end_tags)
        for index in matched_indices
    }
    anchor_closeness = ordering._tag_closeness(start_tags, end_tags)

    forward_order = ordering._greedy_journey_chain(
        matched_indices,
        start_tags,
        start_audio,
        anchor_closeness,
        middle_tags,
        middle_audio,
        closeness_to_end,
    )

    names = ["NearStart", "Bridge", "NearEnd"]
    assert [names[index] for index in forward_order] == ["Bridge", "NearEnd", "NearStart"]


def test_journey_proximity_ordering_bidirectional_consensus_corrects_forward_only_mistake(
    monkeypatch,
) -> None:
    """The bidirectional-consensus regression test. Confirmed live on 2026-08-26: a
    real journey generation placed several start-like R&B/electronic tracks right
    before the ending metal anchor, because the forward-only greedy had already used
    up its best converging candidates earlier and had nothing left to enforce
    continued convergence, so those tracks fell back to an unconstrained pick near
    the end instead of near the start where they belonged.

    This fixture reproduces the same shape with three tracks: "NearStart" (tags
    strongly overlap the start anchor, not the end), "Bridge" (overlaps both), and
    "NearEnd" (overlaps the end anchor, not the start). A forward-only greedy walk
    -- verified directly by calling _greedy_journey_chain in isolation -- produces
    ['Bridge', 'NearEnd', 'NearStart'], stranding NearStart at the very end next to
    the destination. Running the walk a second time from `end` toward `start` and
    merging both walks' opinions by rank pulls NearStart back to the middle instead:
    ['Bridge', 'NearStart', 'NearEnd']. Not the "ideal" ['NearStart', 'Bridge',
    'NearEnd'] -- the two walks genuinely disagree about Bridge/NearStart's exact
    order -- but no longer stranded at the wrong end, which is the defect this
    fixes.
    """
    start = _track("Start", "A")
    end = _track("End", "Z")
    near_start = _track("NearStart", "X")
    bridge = _track("Bridge", "Y")
    near_end = _track("NearEnd", "W")

    tags_by_title = {
        "Start": _tags("rock", "pop"),
        "End": _tags("metal", "doom"),
        "NearStart": _tags("rock", "pop"),
        "Bridge": _tags("rock", "metal"),
        "NearEnd": _tags("metal", "doom"),
    }
    audio_by_title = {
        "Start": _audio(energy=0.5),
        "End": _audio(energy=0.9),
        "NearStart": _audio(energy=0.9),
        "Bridge": _audio(energy=0.5),
        "NearEnd": _audio(energy=0.9),
    }

    async def fake_tags(tracks):
        return [tags_by_title[t["title"]] for t in tracks]

    async def fake_audio(tracks, **kwargs):
        return [audio_by_title[t["title"]] for t in tracks]

    monkeypatch.setattr(ordering, "tag_evidence_for_tracks", fake_tags)
    monkeypatch.setattr(ordering, "audio_evidence_for_tracks", fake_audio)

    result = asyncio.run(
        ordering.order_journey_tracks_by_proximity(
            start, [near_start, bridge, near_end], end
        )
    )

    assert [t["title"] for t in result] == ["Bridge", "NearStart", "NearEnd"]


def test_journey_proximity_ordering_skips_reorder_when_end_has_no_evidence(monkeypatch) -> None:
    middle = [_track("M1", "X"), _track("M2", "X")]

    async def fake_tags(tracks):
        return [ordering.LastfmTagEvidence() for _ in tracks]

    async def fake_audio(tracks, **kwargs):
        return [ReccoBeatsAudioEvidence() for _ in tracks]

    monkeypatch.setattr(ordering, "tag_evidence_for_tracks", fake_tags)
    monkeypatch.setattr(ordering, "audio_evidence_for_tracks", fake_audio)

    result = asyncio.run(
        ordering.order_journey_tracks_by_proximity(
            _track("Start", "A"), middle, _track("End", "B")
        )
    )
    assert result == middle


def test_journey_proximity_ordering_requests_the_energy_fetch_budget_for_audio(
    monkeypatch,
) -> None:
    """ReccoBeats' global rate limit (1 concurrent request, 0.5s minimum interval)
    makes each track cost ~2.5-3.5s serialized; audio_evidence_for_tracks' own
    default budget (6s) completes at most 1-2 tracks out of a journey-sized batch
    (confirmed empirically: 0/20 matched in production). The journey reorder must
    request the same generous budget order_tracks_by_energy already uses for the
    same kind of whole-playlist fetch, not the small-batch default."""
    captured_kwargs: dict = {}

    async def fake_tags(tracks):
        return [ordering.LastfmTagEvidence(track_tags=("rock",)) for _ in tracks]

    async def fake_audio(tracks, **kwargs):
        captured_kwargs.update(kwargs)
        return [ReccoBeatsAudioEvidence() for _ in tracks]

    monkeypatch.setattr(ordering, "tag_evidence_for_tracks", fake_tags)
    monkeypatch.setattr(ordering, "audio_evidence_for_tracks", fake_audio)

    asyncio.run(
        ordering.order_journey_tracks_by_proximity(
            _track("Start", "A"),
            [_track("M1", "X"), _track("M2", "Y")],
            _track("End", "B"),
        )
    )

    assert captured_kwargs.get("timeout_seconds") == ordering._ENERGY_FETCH_BUDGET_SECONDS


def test_journey_proximity_ordering_prefers_tag_compatible_neighbor_over_closer_audio_match(
    monkeypatch,
) -> None:
    """The core regression test: without the tag gate, a pure audio-distance greedy
    would pick track B first (near-identical energy to the start), even though its
    tags are completely disjoint from the start's -- exactly the K-pop/French-house
    failure mode the original track-journey design spec documented and rejected.
    """
    start = _track("Start", "A")
    end = _track("End", "Z")
    track_a = _track("A-compatible", "X")
    track_b = _track("B-audio-close-but-disjoint-tags", "Y")

    tags_by_title = {
        "Start": _tags("rock"),
        "End": _tags("rock"),
        "A-compatible": _tags("rock"),
        "B-audio-close-but-disjoint-tags": _tags("kpop"),
    }
    audio_by_title = {
        "Start": _audio(energy=0.5),
        "End": _audio(energy=0.5),
        "A-compatible": _audio(energy=0.9),
        "B-audio-close-but-disjoint-tags": _audio(energy=0.5),
    }

    async def fake_tags(tracks):
        return [tags_by_title[t["title"]] for t in tracks]

    async def fake_audio(tracks, **kwargs):
        return [audio_by_title[t["title"]] for t in tracks]

    monkeypatch.setattr(ordering, "tag_evidence_for_tracks", fake_tags)
    monkeypatch.setattr(ordering, "audio_evidence_for_tracks", fake_audio)

    result = asyncio.run(
        ordering.order_journey_tracks_by_proximity(start, [track_b, track_a], end)
    )

    assert [t["title"] for t in result] == ["A-compatible", "B-audio-close-but-disjoint-tags"]


def test_journey_proximity_ordering_keeps_unmatched_tracks_in_original_slot(monkeypatch) -> None:
    start = _track("Start", "A")
    end = _track("End", "Z")
    matched_1 = _track("Matched1", "X")
    unmatched = _track("Unmatched", "Y")
    matched_2 = _track("Matched2", "X")

    tags_by_title = {
        "Start": _tags("rock"),
        "End": _tags("rock"),
        "Matched1": _tags("rock"),
        "Unmatched": ordering.LastfmTagEvidence(),
        "Matched2": _tags("rock"),
    }
    audio_by_title = {
        "Start": _audio(energy=0.5),
        "End": _audio(energy=0.5),
        "Matched1": _audio(energy=0.6),
        "Unmatched": ReccoBeatsAudioEvidence(),
        "Matched2": _audio(energy=0.4),
    }

    async def fake_tags(tracks):
        return [tags_by_title[t["title"]] for t in tracks]

    async def fake_audio(tracks, **kwargs):
        return [audio_by_title[t["title"]] for t in tracks]

    monkeypatch.setattr(ordering, "tag_evidence_for_tracks", fake_tags)
    monkeypatch.setattr(ordering, "audio_evidence_for_tracks", fake_audio)

    result = asyncio.run(
        ordering.order_journey_tracks_by_proximity(
            start, [matched_1, unmatched, matched_2], end
        )
    )

    # "Unmatched" has no evidence of either kind and must keep its original slot (index 1).
    assert result[1]["title"] == "Unmatched"
    assert {result[0]["title"], result[2]["title"]} == {"Matched1", "Matched2"}


def test_journey_proximity_ordering_convergence_filter_prefers_closer_candidate(
    monkeypatch,
) -> None:
    """Pins the Tier A2 convergence filter's actual effect with more than one
    tag-compatible candidate present at a step (every other test collapses to a
    single candidate before this filter runs)."""
    start = _track("Start", "A")
    end = _track("End", "Z")
    closer = _track("Closer", "X")
    farther = _track("Farther", "Y")

    tags_by_title = {
        "Start": _tags("rock"),
        "End": _tags("rock", "indie"),
        "Closer": _tags("rock", "indie"),
        "Farther": _tags("rock"),
    }
    audio_by_title = {
        "Start": _audio(energy=0.5),
        "End": _audio(energy=0.5),
        "Closer": _audio(energy=0.9),
        "Farther": _audio(energy=0.5),
    }

    async def fake_tags(tracks):
        return [tags_by_title[t["title"]] for t in tracks]

    async def fake_audio(tracks, **kwargs):
        return [audio_by_title[t["title"]] for t in tracks]

    monkeypatch.setattr(ordering, "tag_evidence_for_tracks", fake_tags)
    monkeypatch.setattr(ordering, "audio_evidence_for_tracks", fake_audio)

    result = asyncio.run(
        ordering.order_journey_tracks_by_proximity(start, [farther, closer], end)
    )

    # Both share a tag with "rock" (start), so both pass Tier A. Start's own
    # closeness to end is 1 ({"rock"}). "Closer" shares 2 tags with end
    # ({"rock","indie"}) and "Farther" shares 1 ({"rock"}) -- both satisfy the
    # convergence threshold (closeness >= 1), so the convergence filter admits
    # both unchanged here (it narrows only when a candidate's closeness regresses
    # below the previous track's; that case is exercised by the "falls back to
    # audio when genre gate empties" test below, and the "keeps unmatched tracks"
    # test above for missing evidence). With both candidates still in the pool,
    # nearest-audio breaks the tie: "Farther" is audio-tied with Start (energy
    # 0.5, distance 0.0) while "Closer" is 0.4 away (energy 0.9), so "Farther" is
    # chosen first despite its lower tag-closeness to "End".
    assert [t["title"] for t in result] == ["Farther", "Closer"]


def test_journey_proximity_ordering_falls_back_to_audio_when_genre_gate_empties(
    monkeypatch,
) -> None:
    """If every remaining track is tag-incompatible with the current position (a real
    edge case, e.g. only one genre cluster left and it's an isolated one), the genre
    gate is dropped for the rest of the run rather than blocking placement."""
    start = _track("Start", "A")
    end = _track("End", "Z")
    orphan_1 = _track("Orphan1", "X")
    orphan_2 = _track("Orphan2", "X")

    tags_by_title = {
        "Start": _tags("rock"),
        "End": _tags("rock"),
        "Orphan1": _tags("kpop"),
        "Orphan2": _tags("jazz"),
    }
    audio_by_title = {
        "Start": _audio(energy=0.5),
        "End": _audio(energy=0.5),
        "Orphan1": _audio(energy=0.9),
        "Orphan2": _audio(energy=0.1),
    }

    async def fake_tags(tracks):
        return [tags_by_title[t["title"]] for t in tracks]

    async def fake_audio(tracks, **kwargs):
        return [audio_by_title[t["title"]] for t in tracks]

    monkeypatch.setattr(ordering, "tag_evidence_for_tracks", fake_tags)
    monkeypatch.setattr(ordering, "audio_evidence_for_tracks", fake_audio)

    result = asyncio.run(
        ordering.order_journey_tracks_by_proximity(start, [orphan_1, orphan_2], end)
    )

    # Neither shares a tag with "rock" (start), so the genre gate empties immediately
    # and falls back to nearest-audio: Orphan2 (energy 0.1) is not closer to start's
    # 0.5 than Orphan1 (0.9) is -- both are equally far, so the original order (stable
    # tie-break) is kept.
    assert [t["title"] for t in result] == ["Orphan1", "Orphan2"]
