import backend.favorites as favorites_module
from backend.favorites import (
    FavoritesRequestLevel,
    favorite_categories_explicitly_requested,
    favorite_categories_mentioned,
    favorite_categories_requested_levels,
)
from backend.main import (
    SeedGenerateRequest,
    SeedTrack,
    _constraint_priority_prompt,
    _favorites_guidance,
    _replenishment_prompt,
    _seed_evidence_guidance,
    _seed_lastfm_evidence_params,
    _seed_mode_instruction,
)


def test_constraint_priority_prompt_keeps_original_request_and_hard_filters():
    prompt = "Italian summer hits released in 2026 only"

    guarded = _constraint_priority_prompt(prompt)

    assert prompt in guarded
    assert "mandatory" in guarded
    assert "never relax" in guarded
    assert "Use musical progression only to order tracks" in guarded


def test_seed_evidence_guidance_folds_lastfm_signals_without_a_second_pass():
    guidance = _seed_evidence_guidance(
        [
            {
                "artist": "Suggested Artist",
                "title": "Suggested Song",
                "lastfm_strategy": "similar_track",
            }
        ],
        seed_mode="strict",
    )

    assert "Suggested Artist" in guidance
    assert "Suggested Song" in guidance
    assert "primary mandatory criterion" in guidance  # strict seed-mode instruction
    assert "Use this evidence only when it satisfies the original request" in guidance
    assert "first-pass ideas" not in guidance.lower()


def test_replenishment_prompt_does_not_relax_constraints_to_fill_count():
    refill = _replenishment_prompt(
        "Italian summer hits released in 2026 only",
        "Estate 2026",
        "Current Italian summer releases.",
        3,
        8,
        [],
        [],
    )

    assert "remains mandatory during replenishment" in refill
    assert "Do not broaden dates, years, language, country" in refill
    assert "satisfy every original constraint" in refill


def test_favorites_guidance_is_empty_when_no_favorites_are_saved(monkeypatch, tmp_path):
    monkeypatch.setattr(favorites_module, "FAVORITES_PATH", tmp_path / "favorites.json")

    assert _favorites_guidance() == ""


def test_favorites_guidance_folds_favorite_artists_and_tracks_as_a_soft_bias(monkeypatch, tmp_path):
    monkeypatch.setattr(favorites_module, "FAVORITES_PATH", tmp_path / "favorites.json")
    favorites_module.add_favorite_artist("Radiohead")
    favorites_module.add_favorite_track(
        {"video_id": "abc123", "title": "Idioteque", "artists": "Radiohead"},
    )

    guidance = _favorites_guidance()

    assert "Radiohead" in guidance
    assert "Idioteque" in guidance
    assert "soft, secondary bias" in guidance
    assert "never override an explicit constraint" in guidance


def test_favorites_guidance_explicit_flags_produce_stronger_wording_per_category(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(favorites_module, "FAVORITES_PATH", tmp_path / "favorites.json")
    favorites_module.add_favorite_artist("Radiohead")
    favorites_module.add_favorite_track(
        {"video_id": "abc123", "title": "Idioteque", "artists": "Radiohead"},
    )

    soft = _favorites_guidance()
    artists_only = _favorites_guidance(artists_level=FavoritesRequestLevel.EXPLICIT)
    tracks_only = _favorites_guidance(tracks_level=FavoritesRequestLevel.EXPLICIT)
    both = _favorites_guidance(
        artists_level=FavoritesRequestLevel.EXPLICIT, tracks_level=FavoritesRequestLevel.EXPLICIT
    )

    assert soft.count("soft, secondary bias") == 2
    assert "explicitly asked to use their favorite artists" in artists_only
    assert "explicitly asked to use their favorite tracks" not in artists_only
    assert artists_only.count("soft, secondary bias") == 1  # tracks stay soft

    assert "explicitly asked to use their favorite tracks" in tracks_only
    assert "explicitly asked to use their favorite artists" not in tracks_only
    assert tracks_only.count("soft, secondary bias") == 1  # artists stay soft

    assert both.count("soft, secondary bias") == 0
    assert "explicitly asked to use their favorite artists" in both
    assert "explicitly asked to use their favorite tracks" in both


def test_favorites_guidance_inspired_level_is_stronger_than_soft_but_not_explicit(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(favorites_module, "FAVORITES_PATH", tmp_path / "favorites.json")
    favorites_module.add_favorite_artist("Radiohead")

    inspired = _favorites_guidance(artists_level=FavoritesRequestLevel.INSPIRED)

    assert "moderately strong bias" in inspired
    assert "explicitly asked to use their favorite artists" not in inspired
    assert inspired.count("soft, secondary bias") == 1  # tracks (unset) stay soft
    assert "never let this bias override" in inspired


def test_favorite_categories_explicitly_requested_detects_multilingual_phrasing_per_category():
    artists_only_prompts = [
        "include my favorite artists please",
        "include my favourite artists please",  # British spelling
        "includi i miei artisti preferiti",
        "ajoute mes artistes préférés",
        "usa mis artistas favoritos",
        "füge meine Lieblingskünstler hinzu",
    ]
    for prompt in artists_only_prompts:
        artists, tracks = favorite_categories_explicitly_requested(prompt)
        assert artists, prompt
        assert not tracks, prompt

    tracks_only_prompts = [
        "add my favorite songs to this playlist",
        "add my favourite songs to this playlist",  # British spelling
        "aggiungi le mie canzoni preferite",
        "ajoute mes chansons préférées",
        "incluye mis canciones favoritas",
        "nutze meine Lieblingssongs",
    ]
    for prompt in tracks_only_prompts:
        artists, tracks = favorite_categories_explicitly_requested(prompt)
        assert tracks, prompt
        assert not artists, prompt

    generic_prompts = [
        "use my favorites for this playlist",
        "use my favourites for this playlist",  # British spelling
        "usa i miei preferiti per questa playlist",
        "utilise mes favoris pour cette playlist",
        "usa mis favoritos para esta playlist",
        "nutze meine Favoriten für diese Playlist",
    ]
    for prompt in generic_prompts:
        artists, tracks = favorite_categories_explicitly_requested(prompt)
        assert artists, prompt
        assert tracks, prompt

    negative_prompts = [
        "Italian summer hits released in 2026 only",
        "my favorite genre is jazz, make me a playlist like that",
        "make it feel like my favorite song, Bohemian Rhapsody",
    ]
    for prompt in negative_prompts:
        artists, tracks = favorite_categories_explicitly_requested(prompt)
        assert not artists, prompt
        assert not tracks, prompt


def test_favorite_categories_requested_levels_downgrades_inspired_by_phrasing():
    inspired_prompts = [
        "Create a playlist inspired by my favourite artists and songs.",
        "Create a playlist inspired by my favorite artists and songs.",
        "una playlist ispirata ai miei artisti preferiti",
        "une playlist inspirée par mes artistes préférés",
        "una playlist inspirada en mis artistas favoritos",
        "eine Playlist inspiriert von meine Lieblingskünstler",
    ]
    for prompt in inspired_prompts:
        artists_level, _tracks_level = favorite_categories_requested_levels(prompt)
        assert artists_level is FavoritesRequestLevel.INSPIRED, prompt

    explicit_prompts = [
        "include my favorite artists please",
        "include my favourite artists please",
    ]
    for prompt in explicit_prompts:
        artists_level, _tracks_level = favorite_categories_requested_levels(prompt)
        assert artists_level is FavoritesRequestLevel.EXPLICIT, prompt

    artists_level, tracks_level = favorite_categories_requested_levels(
        "Italian summer hits released in 2026 only"
    )
    assert artists_level is FavoritesRequestLevel.NONE
    assert tracks_level is FavoritesRequestLevel.NONE


def test_favorite_categories_mentioned_is_true_for_both_inspired_and_explicit_tiers():
    assert favorite_categories_mentioned(
        "Create a playlist inspired by my favourite artists and songs."
    ) == (True, False)
    assert favorite_categories_mentioned("include my favorite artists please") == (True, False)
    assert favorite_categories_mentioned("Italian summer hits released in 2026 only") == (
        False,
        False,
    )


def test_favorites_guidance_is_wired_into_every_generation_prompt_site():
    import inspect

    import backend.main as main_module

    generate_source = inspect.getsource(main_module._generate)
    assert (
        "artists_level, tracks_level = favorite_categories_requested_levels(prompt)"
        in generate_source
    )
    assert "activate_favorite_artist_allowlist(" in generate_source
    assert "initial_prompt += favorites_guidance" in generate_source
    assert "refill_prompt += favorites_guidance" in generate_source
    assert "_seed_favorite_tracks(options, limit=count)" in generate_source

    replace_track_source = inspect.getsource(main_module.replace_track)
    assert (
        "replace_artists_level, replace_tracks_level = favorite_categories_requested_levels(\n"
        "        request.prompt\n    )" in replace_track_source
    )
    assert "activate_favorite_artist_allowlist(" in replace_track_source


def test_seed_modes_have_distinct_similarity_rules():
    strict = _seed_mode_instruction("strict")
    balanced = _seed_mode_instruction("balanced")
    exploratory = _seed_mode_instruction("exploratory")

    assert "primary mandatory criterion" in strict
    assert "close matches supported by Last.fm" in balanced
    assert "real journey" in exploratory
    assert len({strict, balanced, exploratory}) == 3


def test_seed_lastfm_evidence_params_vary_by_mode():
    strict_limit, strict_broaden = _seed_lastfm_evidence_params("strict", 20)
    balanced_limit, balanced_broaden = _seed_lastfm_evidence_params("balanced", 20)
    exploratory_limit, exploratory_broaden = _seed_lastfm_evidence_params("exploratory", 20)

    assert strict_broaden is False
    assert balanced_broaden is False
    assert exploratory_broaden is True
    assert strict_limit < balanced_limit == exploratory_limit


def test_seed_request_defaults_to_balanced_and_accepts_all_modes():
    seed = SeedTrack(video_id="abcdefghijk", title="Seed Song", artists="Seed Artist")

    default_request = SeedGenerateRequest(seed=seed)
    strict_request = SeedGenerateRequest(seed=seed, seed_mode="strict")
    exploratory_request = SeedGenerateRequest(seed=seed, seed_mode="exploratory")

    assert default_request.seed_mode == "balanced"
    assert strict_request.seed_mode == "strict"
    assert exploratory_request.seed_mode == "exploratory"
