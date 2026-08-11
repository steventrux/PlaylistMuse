from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def _text(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_playlist_actions_are_compact_responsive_and_accessible() -> None:
    html = _text("playlist.html")
    script = _text("action-controls.js")
    style = _text("action-controls.css")

    assert '/static/action-controls.css?v=1' in html
    assert '/static/action-controls.js?v=1' in html
    assert html.index('/static/playlist-refine.js?v=2') < html.index('/static/action-controls.js?v=1')

    for label in (
        "Open in YouTube Music",
        "Replace track",
        "Remove track",
        "Move up",
        "Move down",
        "Add track",
        "Refine playlist",
    ):
        assert label in script

    assert "element.setAttribute('aria-label', action.label);" in script
    assert "element.title = action.label;" in script
    assert "new MutationObserver" in script
    assert ".compact-action-label" in style
    assert "@media (hover: hover) and (pointer: fine)" in style
    assert ".compact-action:focus-visible .compact-action-label" in style
    assert "max-width: 190px;" in style
    assert "width: 44px;" in style
    assert "min-width: 44px;" in style
    assert ".playlist-tracks-toolbar" in style
    assert "flex-direction: row;" in style


def test_library_uses_open_for_drafts_and_published_playlists() -> None:
    html = _text("library.html")
    script = _text("action-controls.js")

    assert '/static/action-controls.js?v=1' in html
    assert html.index('/static/library.js?v=11') < html.index('/static/action-controls.js?v=1')
    assert "if (text === 'Edit') link.textContent = 'Open';" in script
    assert "if (text === 'Editing…') link.textContent = 'Opening…';" in script
    assert "if (ariaLabel.startsWith('Edit '))" in script
