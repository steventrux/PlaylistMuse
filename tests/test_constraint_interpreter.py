from backend.constraint_interpreter import _extract_json


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
