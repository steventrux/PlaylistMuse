from backend import playlist_refinement as refinement


def test_positive_artist_interpretation_does_not_become_global_allow_list() -> None:
    interpreted = refinement._RefinementConstraints(
        metadata=refinement.MetadataConstraints(
            allowed_artists=["Litfiba"],
            excluded_artists=["Laura Pausini"],
            allowed_albums=["17 re"],
            release_year_from=2020,
        )
    )
    local = refinement._RefinementConstraints(
        metadata=refinement.MetadataConstraints(excluded_artists=["Alessandra Amoroso"])
    )

    merged = refinement._merge_refinement_constraints(interpreted, local)

    assert merged.metadata.allowed_artists == []
    assert merged.metadata.allowed_albums == []
    assert merged.metadata.release_year_from is None
    assert merged.metadata.excluded_artists == [
        "Laura Pausini",
        "Alessandra Amoroso",
    ]


def test_explicit_album_exclusion_remains_hard() -> None:
    interpreted = refinement._RefinementConstraints(
        metadata=refinement.MetadataConstraints(excluded_albums=["Bad Album"])
    )

    merged = refinement._merge_refinement_constraints(
        interpreted,
        refinement._RefinementConstraints(refinement.MetadataConstraints()),
    )

    assert merged.metadata.excluded_albums == ["Bad Album"]


def test_refinement_prompt_treats_positive_edits_as_targeted_changes() -> None:
    record = {
        "prompt": "Italian rock and pop",
        "playlist": {
            "prompt": "Italian rock and pop",
            "tracks": [
                {"title": "A", "artists": "Artist A"},
                {"title": "B", "artists": "Artist B"},
            ],
        },
        "generation_request": {},
    }

    prompt = refinement._refinement_prompt(
        record,
        "Add Litfiba and make it more rock",
        refinement._RefinementConstraints(refinement.MetadataConstraints()),
    )

    assert "targeted edits" in prompt
    assert "not as filters that every track must satisfy" in prompt
    assert refinement._MAX_REFINEMENT_ATTEMPTS == 3
