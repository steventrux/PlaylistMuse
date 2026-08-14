import asyncio

import pytest

from backend.metadata_validation import (
    TrackMetadata,
    activate_constraints_from_prompt,
    constraints_from_payload,
    extract_metadata_constraints,
    validate_metadata,
)
from backend.national_origin import infer_artist_country
from backend.reccobeats_selector import deterministic_reccobeats_draft
from backend.youtube import _metadata_filter


@pytest.fixture(autouse=True)
def reset_metadata_constraints():
    activate_constraints_from_prompt("generic playlist")
    yield
    activate_constraints_from_prompt("generic playlist")


@pytest.mark.parametrize(
    ("prompt", "country"),
    [
        ("Crea una playlist di musica italiana per un party.", "IT"),
        ("Create a playlist of French music for a party.", "FR"),
        ("Crée une playlist de musique allemande pour une fête.", "DE"),
        ("Crea una playlist de música española para una fiesta.", "ES"),
        ("Erstelle eine Playlist mit britischer Musik für eine Party.", "GB"),
        ("Create a playlist of American songs for a road trip.", "US"),
    ],
)
def test_explicit_national_repertoire_is_detected_locally(prompt, country):
    assert infer_artist_country(prompt) == country


@pytest.mark.parametrize(
    "prompt",
    [
        "Create an Italian-style summer playlist.",
        "Create an Italo disco playlist.",
        "Create a French house playlist.",
        "Create a German techno playlist.",
    ],
)
def test_style_and_genre_labels_do_not_become_country_constraints(prompt):
    assert infer_artist_country(prompt) is None
    assert extract_metadata_constraints(prompt).artist_country is None


def test_real_italian_music_prompt_activates_country_constraint_without_ai():
    constraints = extract_metadata_constraints(
        "Crea una playlist di musica italiana dal 2000 al 2026 adatta per un party."
    )

    assert constraints.artist_country == "IT"
    assert constraints.release_year_from == 2000
    assert constraints.release_year_to == 2026


def test_local_explicit_country_cannot_be_overridden_by_ai_payload():
    fallback = extract_metadata_constraints(
        "Crea una playlist di musica italiana dal 2000 al 2026."
    )
    constraints = constraints_from_payload(
        {
            "artist_country": "US",
            "field_confidence": {"artist_country": 1.0},
        },
        fallback=fallback,
    )

    assert constraints.artist_country == "IT"


def test_recco_fallback_from_real_national_prompt_rejects_foreign_artist(monkeypatch):
    constraints = activate_constraints_from_prompt(
        "Crea una playlist di musica italiana dal 2000 al 2026 con brani popolari per un party."
    )
    assert constraints.artist_country == "IT"

    draft = deterministic_reccobeats_draft(
        [
            {
                "artist": "Italian Artist",
                "title": "Italian Song",
                "source": "reccobeats",
                "reccobeats_id": "it-1",
                "popularity": 72,
            },
            {
                "artist": "Foreign Artist",
                "title": "Foreign Song",
                "source": "reccobeats",
                "reccobeats_id": "us-1",
                "popularity": 85,
            },
        ],
        count=2,
    )
    assert draft is not None

    async def fake_validate(candidate, active, client=None):
        country = "IT" if candidate["artist"] == "Italian Artist" else "US"
        metadata = TrackMetadata(
            artist=candidate["artist"],
            title=candidate["title"],
            artist_country=country,
            original_release_year=2024,
            match_score=0.96,
            confidence="high",
        )
        return validate_metadata(metadata, active)

    monkeypatch.setattr("backend.youtube._read_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.youtube.validate_candidate", fake_validate)

    accepted, rejected = asyncio.run(_metadata_filter(draft["tracks"]))

    assert [candidate["artist"] for candidate in accepted] == ["Italian Artist"]
    assert [candidate["artist"] for candidate in rejected] == ["Foreign Artist"]
    assert rejected[0]["metadata_validation"]["status"] == "invalid"
    assert "artist country US does not match IT" in rejected[0]["metadata_validation"]["violations"]
