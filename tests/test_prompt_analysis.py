import json

from backend.prompt_analysis import parse_analysis


def test_prompt_analysis_accepts_language_independent_semantic_categories() -> None:
    result = parse_analysis(
        json.dumps(
            {
                "dimensions": ["genre", "period", "genre", "unknown"],
                "hard_constraints": 4,
                "soft_constraints": 1,
                "structures": ["progression", "alternation", "unsupported"],
                "relations": 2,
                "ambiguities": ["主観的な条件を定義してください"],
                "conflicts": ["Les deux contraintes sont incompatibles"],
                "missing_information": [],
                "imprecisions": [],
                "possible_typos": ["Möglicher Tippfehler im Künstlernamen"],
            },
            ensure_ascii=False,
        )
    )

    assert result["dimensions"] == ["genre", "period"]
    assert result["structures"] == ["progression", "alternation"]
    assert result["hard_constraints"] == 4
    assert result["ambiguities"] == ["主観的な条件を定義してください"]
    assert result["conflicts"] == ["Les deux contraintes sont incompatibles"]
    assert result["possible_typos"] == ["Möglicher Tippfehler im Künstlernamen"]


def test_prompt_analysis_clamps_counts_and_discards_invalid_shapes() -> None:
    result = parse_analysis(
        json.dumps(
            {
                "dimensions": "genre",
                "hard_constraints": 999,
                "soft_constraints": -2,
                "structures": None,
                "relations": "not-a-number",
                "ambiguities": "subjective",
            }
        )
    )

    assert result["dimensions"] == []
    assert result["hard_constraints"] == 20
    assert result["soft_constraints"] == 0
    assert result["structures"] == []
    assert result["relations"] == 0
    assert result["ambiguities"] == []
