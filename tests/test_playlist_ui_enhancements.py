from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def _text(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_header_navigation_precedes_service_indicators_and_uses_distinct_active_accent() -> None:
    style = _text("header-navigation.css")

    assert "order: 1;" in style
    assert ".header-service-status {\n  order: 2;" in style
    assert "rgba(251, 191, 36" in style
    assert "%23fde68a" in style
    assert "grid-column: 2;" in style
    assert "grid-column: 3;" in style


def test_results_allow_manual_reordering_only_before_publication() -> None:
    html = _text("playlist.html")
    script = _text("playlist.js")
    style = _text("playlist-reorder.css")

    assert "/static/playlist-reorder.css?v=1" in html
    assert 'href="/static/library.html"' in html
    assert "function moveTrack(fromIndex, toIndex)" in script
    assert "if (\n      isPublished()" in script
    assert "handle.draggable = true" in script
    assert "Drag to reorder" in script
    assert "Move up" in script
    assert "Move down" in script
    assert "savePlaylist({immediate: true})" in script
    assert "if (!isPublished())" in script
    assert ".track-result-card.reorderable" in style
    assert ".track-result-card.drag-over" in style


def test_library_cards_are_compact_and_expand_for_full_details() -> None:
    script = _text("library.js")
    style = _text("library.css")

    assert "let expandedLibraryId = null;" in script
    assert "function toggleLibraryCard(card, item)" in script
    assert "library-expand-icon" in script
    assert "library-details" in script
    assert "Original request" in script
    assert "Playlist details" in script
    assert "Created ${formatDate(item.created_at)}" in script
    assert ".library-item.expanded" in style
    assert "grid-template-columns: 58px minmax(0, 1fr) 28px;" in style
    assert "width: 58px;" in style
    assert "width: 138px;" in style
    assert "grid-template-rows: 0fr;" in style
