from __future__ import annotations

import asyncio

from backend import config, llm
from backend import refinement_targets as targets
from backend import youtube
from backend.metadata_validation import MetadataConstraints
from backend.refinement_targets import (
    ArtistAdditionTarget,
    artist_addition_counts,
    explicit_reorder_requested,
    extract_artist_addition_targets,
    preserve_existing_positions,
)


def _track(title: str, artist: str, video_id: str, **extra) -> dict:
    return {"title": title, "artists": artist, "video_id": video_id, **extra}


def test_extracts_quantitative_additions_in_supported_languages() -> None:
    cases = {
        "Add 3 Bryan Adams songs": ArtistAdditionTarget("Bryan Adams", 3),
        "aggiungi 3 canzoni di Bryan Adams": ArtistAdditionTarget("Bryan Adams", 3),
        "añade 3 canciones de Bryan Adams": ArtistAdditionTarget("Bryan Adams", 3),
        "ajoute 3 chansons de Bryan Adams": ArtistAdditionTarget("Bryan Adams", 3),
        "füge 3 Lieder von Bryan Adams hinzu": ArtistAdditionTarget("Bryan Adams", 3),
    }

    for instruction, expected in cases.items():
        assert extract_artist_addition_targets(instruction) == [expected]


def test_extracts_word_counts_in_supported_languages() -> None:
    cases = {
        "Add one Bryan Adams song": ArtistAdditionTarget("Bryan Adams", 1),
        "Add a Bryan Adams song": ArtistAdditionTarget("Bryan Adams", 1),
        "Include twelve David Bowie tracks": ArtistAdditionTarget("David Bowie", 12),
        "aggiungi una canzone di Bryan Adams": ArtistAdditionTarget("Bryan Adams", 1),
        "aggiungi tre canzoni di Bryan Adams": ArtistAdditionTarget("Bryan Adams", 3),
        "añade una canción de Bryan Adams": ArtistAdditionTarget("Bryan Adams", 1),
        "añade cinco canciones de Bryan Adams": ArtistAdditionTarget("Bryan Adams", 5),
        "ajoute une chanson de Bryan Adams": ArtistAdditionTarget("Bryan Adams", 1),
        "ajoute dix chansons de Bryan Adams": ArtistAdditionTarget("Bryan Adams", 10),
        "füge ein Lied von Bryan Adams hinzu": ArtistAdditionTarget("Bryan Adams", 1),
        "füge fünf Lieder von Bryan Adams hinzu": ArtistAdditionTarget("Bryan Adams", 5),
    }

    for instruction, expected in cases.items():
        assert extract_artist_addition_targets(instruction) == [expected]


def test_english_artist_before_track_word_is_supported() -> None:
    assert extract_artist_addition_targets("Include 2 David Bowie tracks") == [
        ArtistAdditionTarget("David Bowie", 2)
    ]


def test_unknown_word_is_not_interpreted_as_a_count() -> None:
    assert extract_artist_addition_targets("Add several Bryan Adams songs") == []


def test_addition_count_only_includes_new_tracks() -> None:
    current = [
        _track("Summer of '69", "Bryan Adams", "old-ba"),
        _track("Old A", "Artist A", "a"),
        _track("Old B", "Artist B", "b"),
    ]
    refined = [
        current[0],
        _track("Heaven", "Bryan Adams", "new-ba-1"),
        _track("Run to You", "Bryan Adams", "new-ba-2"),
    ]
    requested = [ArtistAdditionTarget("Bryan Adams", 2)]

    assert artist_addition_counts(current, refined, requested) == {"Bryan Adams": 2}


def test_ai_guided_fallback_uses_replacement_role_before_catalogue(monkeypatch) -> None:
    current = [
        _track("A", "Artist A", "a"),
        _track("B", "Artist B", "b"),
        _track(
            "C",
            "Artist C",
            "c",
            reason="A restrained power ballad that closes the set warmly.",
        ),
    ]
    requested = [ArtistAdditionTarget("Bryan Adams", 1)]
    calls = {"ai": 0, "resolve": 0, "search": 0}

    async def fake_generate(config_value, prompt: str, count: int) -> dict:
        calls["ai"] += 1
        assert count >= 6
        assert "position 3" in prompt
        assert "previous=Artist B — B" in prompt
        assert "current role=A restrained power ballad" in prompt
        assert "Do not choose merely by popularity" in prompt
        return {
            "title": "Fallback candidates",
            "description": "Contextual replacements",
            "tracks": [
                {
                    "artist": "Bryan Adams",
                    "title": "Heaven",
                    "description": "A slow-burning melodic rock ballad.",
                    "reason": "Matches the warm closing role and ballad pacing.",
                }
            ],
        }

    async def fake_resolve(candidates: list[dict], exclusions: dict) -> tuple[list[dict], list[dict]]:
        calls["resolve"] += 1
        assert exclusions["exclude_covers"] is True
        assert candidates[0]["source"] == "refinement_ai_guided_fallback"
        resolved = _track(
            "Heaven",
            "Bryan Adams",
            "resolved-ba",
            source=candidates[0]["source"],
            reason=candidates[0]["reason"],
        )
        return [resolved], []

    async def fake_search(query: str, limit: int = 8) -> list[dict]:
        calls["search"] += 1
        raise AssertionError("direct catalogue fallback should not run after guided success")

    monkeypatch.setattr(config, "load_config", lambda: object())
    monkeypatch.setattr(llm, "generate_playlist_draft", fake_generate)
    monkeypatch.setattr(youtube, "resolve_candidates", fake_resolve)
    monkeypatch.setattr(youtube, "search_songs", fake_search)

    repaired, unresolved = asyncio.run(
        targets.repair_artist_addition_targets(
            current,
            current,
            current,
            requested,
            exclusions={
                "exclude_live": True,
                "exclude_covers": True,
                "exclude_remixes": True,
            },
            metadata_constraints=MetadataConstraints(),
        )
    )

    assert calls == {"ai": 1, "resolve": 1, "search": 0}
    assert unresolved == []
    assert artist_addition_counts(current, repaired, requested) == {"Bryan Adams": 1}
    stable = preserve_existing_positions(current, repaired)
    assert [track["title"] for track in stable] == ["A", "B", "Heaven"]
    assert stable[-1]["source"] == "refinement_ai_guided_fallback"
    assert "warm closing role" in stable[-1]["reason"]


def test_catalogue_is_last_resort_when_guided_ai_fails(monkeypatch) -> None:
    current = [
        _track("A", "Artist A", "a"),
        _track("B", "Artist B", "b"),
        _track("C", "Artist C", "c"),
    ]
    requested = [ArtistAdditionTarget("Bryan Adams", 1)]
    calls = {"ai": 0, "search": 0}

    async def fake_generate(config_value, prompt: str, count: int) -> dict:
        calls["ai"] += 1
        raise ValueError("provider unavailable")

    async def fake_search(query: str, limit: int = 8) -> list[dict]:
        calls["search"] += 1
        assert query == "Bryan Adams"
        assert limit >= 16
        return [
            _track("Heaven", "Bryan Adams", "catalogue-ba"),
            _track("Unrelated", "Other Artist", "other"),
        ]

    async def fake_resolve(candidates: list[dict], exclusions: dict) -> tuple[list[dict], list[dict]]:
        assert exclusions["exclude_covers"] is True
        assert [(item["artist"], item["title"]) for item in candidates] == [
            ("Bryan Adams", "Heaven")
        ]
        return [
            _track(
                "Heaven",
                "Bryan Adams",
                "resolved-ba",
                source="refinement_catalogue_fallback",
            )
        ], []

    monkeypatch.setattr(config, "load_config", lambda: object())
    monkeypatch.setattr(llm, "generate_playlist_draft", fake_generate)
    monkeypatch.setattr(youtube, "search_songs", fake_search)
    monkeypatch.setattr(youtube, "resolve_candidates", fake_resolve)

    repaired, unresolved = asyncio.run(
        targets.repair_artist_addition_targets(
            current,
            current,
            current,
            requested,
            exclusions={
                "exclude_live": True,
                "exclude_covers": True,
                "exclude_remixes": True,
            },
            metadata_constraints=MetadataConstraints(),
        )
    )

    assert calls == {"ai": 1, "search": 1}
    assert unresolved == []
    assert len(repaired) == 3
    assert artist_addition_counts(current, repaired, requested) == {"Bryan Adams": 1}
    stable = preserve_existing_positions(current, repaired)
    assert [track["title"] for track in stable] == ["A", "B", "Heaven"]
    assert stable[-1]["source"] == "refinement_catalogue_fallback"


def test_existing_tracks_keep_their_original_slots_without_reorder_request() -> None:
    current = [
        _track("A", "Artist A", "a"),
        _track("B", "Artist B", "b"),
        _track("C", "Artist C", "c"),
        _track("D", "Artist D", "d"),
    ]
    refined = [
        current[2],
        _track("New 1", "Bryan Adams", "n1"),
        current[0],
        _track("New 2", "Bryan Adams", "n2"),
    ]

    stable = preserve_existing_positions(current, refined)

    assert [track["title"] for track in stable] == ["A", "New 1", "C", "New 2"]


def test_reorder_detection_is_explicit_and_multilingual() -> None:
    assert explicit_reorder_requested("reorder from oldest to newest")
    assert explicit_reorder_requested("riordina dalla più vecchia alla più recente")
    assert explicit_reorder_requested("ordena de la más antigua a la más reciente")
    assert explicit_reorder_requested("trie de la plus ancienne à la plus récente")
    assert explicit_reorder_requested("sortiere vom ältesten zum neuesten")
    assert not explicit_reorder_requested("Add 3 Bryan Adams songs")