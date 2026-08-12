from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def _text(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_refinement_moves_from_library_to_playlist_editor() -> None:
    library = _text("library.html")
    playlist = _text("playlist.html")
    library_script = _text("library.js")

    assert "/static/library-refine.css" not in library
    assert "/static/library-refine.js" not in library
    assert "PlaylistMuseLibraryRefine" not in library_script
    assert 'id="refine-playlist"' in playlist
    assert '>Playlist Studio</button>' in playlist
    assert '/static/playlist-refine.css?v=5' in playlist
    assert '/static/playlist-refine.js?v=5' in playlist


def test_refinement_uses_preview_before_apply_and_flushes_current_draft() -> None:
    script = _text("playlist-refine.js")

    assert "editor.flushPersistence()" in script
    assert "/studio-preview`" in script
    assert "/studio-apply`" in script
    assert "Target only the tracks you want the AI to edit." in script
    assert "previewPlaylist = payload.playlist;" in script
    assert "Apply changes" in script
    assert "textarea.addEventListener('input', resetPreview);" in script
    assert "editor.applyRecord(record);" in script
    assert "`${reordered} repositioned`" in script


def test_playlist_studio_exposes_target_and_lock_controls() -> None:
    script = _text("playlist-refine.js")
    style = _text("playlist-refine.css")

    assert "All tracks" in script
    assert "Selected tracks" in script
    assert "playlist-studio-target" in script
    assert "playlist-studio-lock" in script
    assert "target_positions: targetPositions" in script
    assert "locked_positions: lockedPositions" in script
    assert "Select at least one unlocked track to refine." in script
    assert ".playlist-studio-track-list" in style
    assert "max-block-size: min(42vh, 20rem);" in style


def test_playlist_studio_lock_uses_supplied_icons_at_row_edge() -> None:
    script = _text("playlist-refine.js")
    style = _text("playlist-refine.css")
    open_icon = _text("lock-open-alt.svg")
    closed_icon = _text("lock.svg")

    assert "function createLockIcon()" in script
    assert "row.append(targetWrap, text, lockWrap);" in script
    assert "text.append(titleText, lockWrap, artistText);" not in script
    assert "icon.innerHTML" not in script
    assert "grid-template-columns: auto minmax(0, 1fr) auto;" in style
    assert "url('/static/lock-open-alt.svg')" in style
    assert "url('/static/lock.svg')" in style
    assert "color: var(--text-muted);" in style
    assert ".playlist-studio-lock-wrap:has(input:checked)" in style
    assert "color: var(--text-primary);" in style
    assert "<svg" in open_icon
    assert "<svg" in closed_icon


def test_refinement_preview_shows_only_changes_not_full_track_lists() -> None:
    script = _text("playlist-refine.js")
    style = _text("playlist-refine.css")

    assert "function renderComparison(proposed)" in script
    assert "const removed = currentTracks.filter" in script
    assert "const added = proposedTracks.filter" in script
    assert "createChangeGroup('Removed'" in script
    assert "createChangeGroup('Added'" in script
    assert "playlist-refine-changes" in script
    assert "createTrackList" not in script
    assert "Current playlist" not in script
    assert "Proposed playlist" not in script
    assert "playlist-refine-preview-list" not in style
    assert "playlist-refine-track-area" not in style
    assert ".playlist-refine-changes" in style
    assert ".playlist-refine-track-removed" in style
    assert "text-decoration: line-through;" in style
    assert ".playlist-refine-track-added" in style


def test_refinement_panel_remains_compact() -> None:
    style = _text("playlist-refine.css")
    editor_style = _text("playlist-editor.css")

    assert ".playlist-refine-actions" in style
    assert ".playlist-refine-panel" in editor_style
    assert "padding: 14px;" in editor_style
    assert "border-radius: 14px;" in editor_style
    assert "max-height: 300px;" not in style
    assert "max-block-size: min(42vh, 20rem);" in style
