from backend.refinement_targets import (
    ArtistAdditionTarget,
    artist_addition_counts,
    explicit_reorder_requested,
    extract_artist_addition_targets,
    preserve_existing_positions,
)


def _track(title: str, artist: str, video_id: str) -> dict:
    return {"title": title, "artists": artist, "video_id": video_id}


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


def test_english_artist_before_track_word_is_supported() -> None:
    assert extract_artist_addition_targets("Include 2 David Bowie tracks") == [
        ArtistAdditionTarget("David Bowie", 2)
    ]


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
    targets = [ArtistAdditionTarget("Bryan Adams", 2)]

    assert artist_addition_counts(current, refined, targets) == {"Bryan Adams": 2}


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
