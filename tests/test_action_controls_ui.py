from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def _text(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_playlist_actions_are_compact_responsive_and_accessible() -> None:
    html = _text("playlist.html")
    script = _text("action-controls.js")
    style = _text("action-controls.css")

    assert '/static/action-controls.css?v=9' in html
    assert '/static/action-controls.js?v=8' in html
    assert html.index('/static/playlist-refine.js?v=7') < html.index('/static/action-controls.js?v=8')

    for label in (
        "Open in YouTube Music",
        "Replace track",
        "Remove track",
        "Move up",
        "Move down",
        "Add track",
        "Playlist Studio",
        "Give feedback",
    ):
        assert label in script

    assert "'#playlist-feedback'" in script
    assert "if (element.id === 'playlist-feedback') return 'feedback';" in script
    assert "feedback: {label: 'Give feedback', icon: ICONS.feedback}" in script
    assert ".playlist-feedback-action.compact-action" in style

    assert "'#playlist-positive-feedback'" in script
    assert "if (element.id === 'playlist-positive-feedback') return 'loved';" in script
    assert "loved: {label: 'This got it right', icon: ICONS.loved}" in script
    assert "element.setAttribute('aria-label', action.label);" in script
    assert "element.title = action.label;" in script
    assert "new MutationObserver" in script
    assert ".compact-action-label" in style
    assert "@media (hover: hover) and (pointer: fine)" in style
    assert ".compact-action:focus-visible .compact-action-label" in style
    assert "max-width: 190px;" in style
    assert "width: 44px;" in style
    assert "min-width: 44px;" in style
    assert "max-width: 44px;" in style
    assert "flex: 0 0 44px;" in style
    assert ".compact-action.is-loading .generation-label" in style
    assert ".compact-action.is-loading .generation-dots" in style
    assert "display: none;" in style
    assert ".playlist-tracks-toolbar" in style
    assert "flex-direction: row;" in style
    assert ".playlist-toolbar-actions" in style
    assert "margin-left: auto;" in style
    assert "justify-content: flex-end;" in style
    assert "flex-wrap: nowrap;" in style


def test_library_uses_open_for_drafts_and_published_playlists() -> None:
    html = _text("library.html")
    script = _text("action-controls.js")

    assert '/static/action-controls.js?v=8' in html
    assert html.index('/static/library.js?v=15') < html.index('/static/action-controls.js?v=8')
    assert "if (text === 'Edit') link.textContent = 'Open';" in script
    assert "if (text === 'Editing…') link.textContent = 'Opening…';" in script
    assert "if (ariaLabel.startsWith('Edit '))" in script
