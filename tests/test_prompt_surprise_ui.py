from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def _text(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_random_prompt_control_uses_shared_generator_with_concise_profiles() -> None:
    html = _text("index.html")
    script = _text("prompt-surprise.js")
    style = _text("prompt-surprise.css")

    assert '/static/prompt-surprise.css?v=2' in html
    assert '/static/prompt-surprise.js?v=2' in html
    assert 'id="prompt-surprise"' in html
    assert 'class="prompt-input-shell"' in html
    assert 'title="Surprise me"' in html
    assert "const MUSIC_FAMILIES = [" in script
    assert "const MOODS = [" in script
    assert "const CONTEXTS = [" in script
    assert "const CREATIVE_DIRECTIONS = [" in script
    assert "const PROFILES = {" in script
    assert "minWords: 10" in script
    assert "maxWords: 20" in script
    assert "minWords: 18" in script
    assert "maxWords: 36" in script
    assert "creativeChance: 0.28" in script
    assert "function buildPrompt(profileName = 'surprise')" in script
    assert "const example = buildPrompt('example');" in script
    assert "let next = buildPrompt('surprise');" in script
    assert "prompt.placeholder = example;" in script
    assert "prompt.value = next;" in script
    assert "prompt.dispatchEvent(new Event('input', {bubbles: true}));" in script
    assert "button?.addEventListener('click', surpriseMe);" in script
    assert "VOCAL_DIRECTIONS" not in script
    assert "SEQUENCING" not in script
    assert ".prompt-surprise" in style
    assert "opacity: .78;" in style


def test_random_prompt_selects_subset_of_dimensions_instead_of_all_of_them() -> None:
    script = _text("prompt-surprise.js")

    assert "extraDimensions: () => (Math.random() < 0.72 ? 1 : 2)" in script
    assert "extraDimensions: () => (Math.random() < 0.72 ? 2 : 3)" in script
    assert ".slice(0, profile.extraDimensions());" in script
    assert "Math.random() < profile.creativeChance" in script
    assert "for (let attempt = 0; attempt < 32; attempt += 1)" in script
    assert "words >= profile.minWords && words <= profile.maxWords" in script


def test_random_prompt_icon_is_compact_three_dimensional_die() -> None:
    html = _text("index.html")
    style = _text("prompt-surprise.css")

    assert 'class="prompt-surprise-face"' in html
    assert 'd="M12 2.8 20 7.3v9.4l-8 4.5-8-4.5V7.3Z"' in html
    assert 'd="M4 7.3 12 11.8 20 7.3M12 11.8v9.4"' in html
    assert html.count('class="prompt-surprise-pip"') == 6
    assert ".prompt-surprise .prompt-surprise-face" in style
    assert "fill-opacity: .07;" in style
    assert ".prompt-surprise .prompt-surprise-pip" in style
    assert "width: 18px;" in style


def test_playlist_navigation_icons_have_contextual_tooltips() -> None:
    home = _text("index.html")
    results = _text("playlist.html")
    library = _text("library.html")

    assert 'href="/static/library.html" aria-label="My playlists" title="My playlists"' in home
    assert 'href="/static/library.html" aria-label="My playlists" title="My playlists"' in results
    assert 'href="/" aria-label="Home" title="Home"' in library
