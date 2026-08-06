import asyncio

from backend.prompt_validation import (
    _augment_explicit_entity_constraints,
    _local_temporal_assessment,
    assess_interpretation,
    assess_prompt,
)


def test_impossible_prompt_preserves_user_facing_reason():
    assessment = assess_interpretation(
        {
            "constraint_status": "impossible",
            "status_reasons": [
                "Un brano non può essere pubblicato negli anni '90 e dopo il 2000."
            ],
            "contradictions": ["The requested release periods have no overlap."],
        }
    )

    assert assessment.status == "impossible"
    assert assessment.reasons == (
        "Un brano non può essere pubblicato negli anni '90 e dopo il 2000.",
    )


def test_ambiguous_prompt_preserves_warning_reason():
    assessment = assess_interpretation(
        {
            "constraint_status": "ambiguous",
            "status_reasons": [
                "Non è chiaro se 'Europe' indichi la band o la provenienza geografica."
            ],
        }
    )

    assert assessment.status == "ambiguous"
    assert assessment.reasons


def test_valid_prompt_has_no_warning():
    assessment = assess_interpretation(
        {
            "constraint_status": "valid",
            "status_reasons": [],
            "contradictions": [],
        }
    )

    assert assessment.status == "valid"
    assert assessment.reasons == ()


def test_legacy_impossible_contradiction_is_detected():
    assessment = assess_interpretation(
        {
            "contradictions": [
                "The requested date ranges are incompatible and have no overlap."
            ]
        }
    )

    assert assessment.status == "impossible"


def test_local_temporal_conflict_detects_decade_after_cutoff():
    assessment = _local_temporal_assessment(
        "musica degli anni 90 pubblicata dopo il 2000"
    )

    assert assessment is not None
    assert assessment.status == "impossible"
    assert "2001" in assessment.reasons[0]
    assert "1999" in assessment.reasons[0]


def test_compatible_temporal_constraints_are_not_blocked_locally():
    assessment = _local_temporal_assessment(
        "musica degli anni 90 pubblicata dopo il 1994"
    )

    assert assessment is None


def test_local_impossible_prompt_skips_ai_interpreter(monkeypatch):
    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("AI interpreter must not be called for a local contradiction")

    monkeypatch.setattr(
        "backend.prompt_validation.interpret_constraints",
        fail_if_called,
    )

    assessment = asyncio.run(
        assess_prompt(
            object(),  # type: ignore[arg-type]
            "musica degli anni 90 pubblicata dopo il 2000",
        )
    )

    assert assessment.status == "impossible"


def test_explicit_album_and_excluded_artist_are_extracted_locally():
    payload = _augment_explicit_entity_constraints(
        "musica rock anni 90, includi album Load, escludi i Metallica",
        {},
    )

    assert payload["allowed_albums"] == ["Load"]
    assert payload["excluded_artists"] == ["Metallica"]


def test_verified_album_artist_conflict_is_impossible_with_empty_ai_payload(monkeypatch):
    captured_payload = None

    async def interpreted(*_args, **_kwargs):
        return {}

    async def relationship(payload):
        nonlocal captured_payload
        captured_payload = payload
        return "Load", "Metallica"

    monkeypatch.setattr(
        "backend.prompt_validation.interpret_constraints",
        interpreted,
    )
    monkeypatch.setattr(
        "backend.prompt_validation.find_album_artist_conflict",
        relationship,
    )

    assessment = asyncio.run(
        assess_prompt(
            object(),  # type: ignore[arg-type]
            "musica rock anni 90, includi album Load, escludi i Metallica",
        )
    )

    assert captured_payload is not None
    assert captured_payload["allowed_albums"] == ["Load"]
    assert captured_payload["excluded_artists"] == ["Metallica"]
    assert assessment.status == "impossible"
    assert "Load" in assessment.reasons[0]
    assert "Metallica" in assessment.reasons[0]


def test_non_conflicting_album_artist_relationship_stays_valid(monkeypatch):
    async def interpreted(*_args, **_kwargs):
        return {}

    async def no_relationship_conflict(payload):
        assert payload["allowed_albums"] == ["Load"]
        assert payload["excluded_artists"] == ["Nirvana"]
        return None

    monkeypatch.setattr(
        "backend.prompt_validation.interpret_constraints",
        interpreted,
    )
    monkeypatch.setattr(
        "backend.prompt_validation.find_album_artist_conflict",
        no_relationship_conflict,
    )

    assessment = asyncio.run(
        assess_prompt(
            object(),  # type: ignore[arg-type]
            "includi album Load, escludi i Nirvana",
        )
    )

    assert assessment.status == "valid"
