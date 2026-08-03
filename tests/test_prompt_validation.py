from backend.prompt_validation import assess_interpretation


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
