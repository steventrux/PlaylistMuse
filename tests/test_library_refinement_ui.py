from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def _text(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_library_loads_refinement_assets_before_library_renderer() -> None:
    html = _text("library.html")

    assert '/static/library-refine.css?v=3' in html
    refine = '<script src="/static/library-refine.js?v=2"></script>'
    library = '<script src="/static/library.js?v=8"></script>'
    assert refine in html
    assert library in html
    assert html.index(refine) < html.index(library)


def test_refine_action_is_installed_only_for_drafts() -> None:
    library = _text("library.js")
    refine = _text("library-refine.js")

    assert "if (item.status === 'draft')" in library
    assert "window.PlaylistMuseLibraryRefine?.install" in library
    assert "if (!item || item.status !== 'draft'" in refine
    assert "refine.textContent = 'Refine';" in refine
    assert "Fine-tune this draft with another prompt" in refine


def test_refinement_uses_preview_before_apply_and_invalidates_stale_preview() -> None:
    script = _text("library-refine.js")

    assert "/refine-preview`" in script
    assert "/refine-apply`" in script
    assert "The current draft stays unchanged until you apply the preview." in script
    assert "previewPlaylist = payload.playlist;" in script
    assert "applyButton.classList.remove('hidden');" in script
    assert "textarea.addEventListener('input', resetPreview);" in script
    assert "previewPlaylist = null;" in script
    assert "Apply changes" in script


def test_refine_loads_current_tracks_when_panel_opens() -> None:
    script = _text("library-refine.js")

    assert "async function loadCurrentPlaylist()" in script
    assert "{cache: 'no-store'}" in script
    assert "currentPlaylist = record.playlist;" in script
    assert "renderCurrentPlaylist();" in script
    assert "trackHeading.textContent = 'Current playlist';" in script
    assert "void loadCurrentPlaylist();" in script


def test_refinement_preview_marks_removed_and_added_tracks_without_guessing_pairs() -> None:
    script = _text("library-refine.js")
    style = _text("library-refine.css")

    assert "function renderComparison(proposed)" in script
    assert "const removed = currentTracks.filter" in script
    assert "const added = proposedTracks.filter" in script
    assert "createChangeGroup('Removed'" in script
    assert "createChangeGroup('Added'" in script
    assert "proposedHeading.textContent = 'Proposed playlist';" in script
    assert ".library-refine-track-removed" in style
    assert "text-decoration: line-through;" in style
    assert ".library-refine-track-added" in style
    assert "color: #86efac;" in style


def test_refinement_textarea_leaves_room_for_focus_ring() -> None:
    style = _text("library-refine.css")

    assert "width: calc(100% - 8px);" in style
    assert "margin-inline: 4px;" in style
    assert "box-sizing: border-box;" in style


def test_refinement_panel_is_visually_grouped_and_compact() -> None:
    style = _text("library-refine.css")

    assert ".library-refine-panel" in style
    assert "padding: 14px;" in style
    assert "border-radius: 14px;" in style
    assert "background: rgba(8, 11, 27, .34);" in style
    assert "min-height: 78px;" in style
    assert ".library-refine-hint" in style
    assert "border-left: 2px solid" in style
    assert ".library-refine-actions" in style
    assert "justify-content: flex-end;" in style


def test_refinement_track_area_is_compact_and_scrollable() -> None:
    style = _text("library-refine.css")

    assert ".library-refine-panel" in style
    assert ".library-refine-track-area" in style
    assert "max-height: 300px;" in style
    assert "overflow: auto;" in style
    assert ".library-refine-actions" in style
