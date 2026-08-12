import pytest

from backend.constraint_interpreter import _extract_json, _guard_artist_country


def test_extracts_constraint_json_from_provider_text():
    payload = _extract_json(
        '```json\n{"allowed_artists":["Metallica"],"confidence":"high"}\n```'
    )

    assert payload["allowed_artists"] == ["Metallica"]
    assert payload["confidence"] == "high"


def test_constraint_payload_can_represent_non_latin_requests():
    payload = _extract_json(
        '{"allowed_artists":["坂本龍一"],"excluded_artists":[],"allowed_albums":[],"excluded_albums":[],"release_year":null,"release_year_from":1980,"release_year_to":1989,"artist_country":null,"confidence":"high"}'
    )

    assert payload["allowed_artists"] == ["坂本龍一"]
    assert payload["release_year_from"] == 1980
    assert payload["release_year_to"] == 1989


@pytest.mark.parametrize(
    "prompt",
    [
        "Crea una playlist di musica italiana dal 2000 ad oggi adatta per un party.",
        "Create a playlist of Italian music for a party.",
        "Crée une playlist de musique italienne pour une fête.",
        "Crea una playlist de música italiana para una fiesta.",
        "Erstelle eine Playlist mit italienischer Musik für eine Party.",
    ],
)
def test_generic_national_music_does_not_become_artist_country_constraint(prompt):
    payload = {
        "artist_country": "IT",
        "field_confidence": {"artist_country": 0.99},
    }

    guarded = _guard_artist_country(prompt, payload)

    assert guarded["artist_country"] is None
    assert guarded["field_confidence"]["artist_country"] == 0.0


@pytest.mark.parametrize(
    "prompt",
    [
        "Solo brani di artisti italiani dal 2000 ad oggi.",
        "Only tracks by Italian artists from 2000 onward.",
        "Uniquement des titres d'artistes italiens depuis 2000.",
        "Solo canciones de artistas italianos desde 2000.",
        "Nur Songs italienischer Künstler ab 2000.",
    ],
)
def test_explicit_artist_nationality_keeps_artist_country_constraint(prompt):
    payload = {
        "artist_country": "IT",
        "field_confidence": {"artist_country": 0.99},
    }

    guarded = _guard_artist_country(prompt, payload)

    assert guarded["artist_country"] == "IT"
    assert guarded["field_confidence"]["artist_country"] == 0.99
