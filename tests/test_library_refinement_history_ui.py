from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def _text(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_library_loads_dedicated_refinement_history_styles() -> None:
    html = _text("library.html")
    style = _text("library-refinement-history.css")

    assert '/static/library-refinement-history.css?v=1' in html
    assert ".library-refinement-history-line:has(strong)" in style
    assert ".library-refinement-history-line:not(:has(strong))" in style
    assert "border-left: 2px solid" in style
    assert "background: rgba(8, 11, 27, .28);" in style
    assert "text-transform: uppercase;" in style


def test_refinement_history_keeps_existing_rendering_contract() -> None:
    script = _text("library.js")

    assert "function renderRefinementHistory(block, prompts)" in script
    assert "library-refinement-history-line" in script
    assert "strong.textContent = 'Refinements';" in script
    assert "paragraph.textContent = `${index + 1}. ${prompt}`;" in script
