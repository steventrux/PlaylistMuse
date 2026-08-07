from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def _text(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_random_prompt_control_uses_shared_combinatorial_generator_for_example_and_click() -> None:
    html = _text("index.html")
    script = _text("prompt-surprise.js")
    style = _text("prompt-surprise.css")

    assert '/static/prompt-surprise.css?v=1' in html
    assert '/static/prompt-surprise.js?v=1' in html
    assert 'id="prompt-surprise"' in html
    assert 'class="prompt-input-shell"' in html
    assert 'title="Surprise me"' in html
    assert "const MUSIC_FAMILIES = [" in script
    assert "const CONTEXTS = [" in script
    assert "const ENERGY_ARCS = {" in script
    assert "const MOODS = [" in script
    assert "const DISCOVERY = [" in script
    assert "const VOCAL_DIRECTIONS = [" in script
    assert "const SEQUENCING = [" in script
    assert "const TEMPLATES = [" in script
    assert "function buildPrompt()" in script
    assert "const example = buildPrompt();" in script
    assert "prompt.placeholder = example;" in script
    assert "prompt.value = next;" in script
    assert "prompt.dispatchEvent(new Event('input', {bubbles: true}));" in script
    assert "button?.addEventListener('click', surpriseMe);" in script
    assert ".prompt-surprise" in style
    assert "opacity: .78;" in style


def test_playlist_navigation_icons_have_contextual_tooltips() -> None:
    home = _text("index.html")
    results = _text("playlist.html")
    library = _text("library.html")

    assert 'href="/static/library.html" aria-label="My playlists" title="My playlists"' in home
    assert 'href="/static/library.html" aria-label="My playlists" title="My playlists"' in results
    assert 'href="/" aria-label="Home" title="Home"' in library
