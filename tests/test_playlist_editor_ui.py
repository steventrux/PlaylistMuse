from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def _text(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_library_is_read_only_and_uses_contextual_open_label() -> None:
    html = _text("library.html")
    script = _text("library.js")
    tags = _text("library-tags.js")

    assert "/static/library-refine.js" not in html
    assert "/static/library-refine.css" not in html
    assert "item.status === 'draft' ? 'Edit' : 'Open'" in script
    assert "PlaylistMuseLibraryRefine" not in script
    assert "tagTools?.install" not in script
    assert "method: 'PUT'" not in tags
    assert "function install(" not in tags


def test_playlist_page_centralizes_draft_editing_controls() -> None:
    html = _text("playlist.html")

    assert 'id="playlist-description"' in html
    assert 'maxlength="2000"' in html
    assert 'rows="4"' in html
    assert html.index('class="playlist-title-editor"') < html.index('class="playlist-overview"')
    assert 'id="playlist-draft-actions" class="playlist-draft-actions hidden"' in html
    assert 'id="add-track"' in html
    assert 'id="refine-playlist"' in html
    assert '>Playlist Studio</button>' in html
    assert '/static/playlist-header.css?v=13' in html
    assert '/static/playlist-editor.css?v=8' in html
    assert '/static/playlist-add-track.js?v=3' in html
    assert '/static/playlist-refine.js?v=7' in html


def test_playlist_autosave_status_tracks_persistent_library_writes() -> None:
    html = _text("playlist.html")
    script = _text("playlist-save-status.js")
    style = _text("playlist-header.css")

    status_script = '<script src="/static/playlist-save-status.js?v=2"></script>'
    playlist_script = '<script src="/static/playlist.js?v=28"></script>'
    assert status_script in html
    assert html.index(status_script) < html.index(playlist_script)
    assert "saving: 'Saving…'" in script
    assert "saved: 'Saved'" in script
    assert "error: 'Save failed'" in script
    assert "const SAVED_VISIBLE_MS = 1400;" in script
    assert "let userChangeArmed = false;" in script
    assert "let visibleCycle = false;" in script
    assert "document.body.append(status);" in script
    assert "function scheduleSavedHide()" in script
    assert "if (state === 'saving' && userChangeArmed) visibleCycle = true;" in script
    assert "['input', 'change', 'click', 'dragstart', 'drop']" in script
    assert "window.addEventListener('pageshow', hideStatus);" in script
    assert "document.body.dataset.librarySaveState" in script
    assert "method === 'PUT'" in script
    assert "path.endsWith('/tags/suggest')" in script
    assert "path.endsWith('/refine-apply')" in script
    assert "path.endsWith('/studio-apply')" in script
    assert "if (!response.ok) batchFailed = true;" in script
    assert "playlist.youtube_playlist?.url" in script
    assert "role', 'status'" in script
    assert "position: fixed;" in style
    assert "bottom: 18px;" in style
    assert "left: calc(50% + 444px);" in style
    assert ".playlist-save-status[data-state=\"saving\"]" in style
    assert ".playlist-save-status[data-state=\"error\"]" in style
    assert "body.playlist-readonly .playlist-save-status" in style


def test_add_track_searches_existing_youtube_catalogue_and_appends_safely() -> None:
    script = _text("playlist-add-track.js")

    assert "const SEARCH_ENDPOINT = '/api/seeds/search';" in script
    assert "const SEARCH_LIMIT = 8;" in script
    assert "const MAX_TRACKS = 100;" in script
    assert "duplicateTrack(playlist, track)" in script
    assert "This track is already in the playlist." in script
    assert "playlist.tracks.push({" in script
    assert "Added manually from YouTube Music." in script
    assert "Added manually to this playlist." in script
    assert "to the end of the playlist" in script


def test_manual_add_and_remove_are_recorded_in_refinement_history() -> None:
    script = _text("playlist-add-track.js")

    assert "function appendManualHistory(kind, track)" in script
    assert "appendManualHistory('manual_add', track);" in script
    assert "appendManualHistory('manual_remove', track);" in script
    assert "prompt: `${action}: ${trackHistoryText(track)}`" in script
    assert "request.refinements = refinements;" in script
    assert "applied_at: new Date().toISOString()" in script


def test_positive_feedback_button_exists_with_matching_gating_to_negative_feedback() -> None:
    html = _text("playlist.html")
    script = _text("playlist-positive-feedback.js")
    negative_script = _text("playlist-feedback.js")

    assert 'id="playlist-positive-feedback"' in html
    assert '/static/playlist-positive-feedback.js?v=4' in html
    assert '/static/action-controls.js?v=8' in html
    assert "const ENDPOINT = '/api/quality/local-feedback';" in script
    # Same session-storage keys and flag-based gating as the existing
    # negative-feedback button, deliberately.
    assert "STORAGE_KEY = 'playlistmuse-generated-playlist'" in script
    assert "if (!playlist.playlistmuseFreshlyGenerated) return;" in script
    assert "new URLSearchParams(window.location.search).has('id')" not in script
    assert "STORAGE_KEY = 'playlistmuse-generated-playlist'" in negative_script
    assert "if (!playlist.playlistmuseFreshlyGenerated) return;" in negative_script
    assert "new URLSearchParams(window.location.search).has('id')" not in negative_script

    app_script = _text("app.js")
    assert "data.playlistmuseFreshlyGenerated = true;" in app_script

    playlist_script = _text("playlist.js")
    assert "delete playlist.playlistmuseFreshlyGenerated;" in playlist_script
    assert "delete playlist.playlistmuseTasteCaptured;" in playlist_script
    # Mutation observer fix: target .compact-action-label span, not button.textContent
    assert "const label = button.querySelector('.compact-action-label');" in script
    assert "if (label) label.textContent = CONFIRMED_LABEL;" in script
    # Capture state survives a page reload of the same freshly generated
    # playlist, not just the remainder of one in-memory page load.
    assert "playlist.playlistmuseTasteCaptured = true;" in script
    assert "if (playlist.playlistmuseTasteCaptured) {" in script
