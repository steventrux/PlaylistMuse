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
    assert 'id="playlist-draft-actions"' in html
    assert 'id="add-track"' in html
    assert 'id="refine-playlist"' in html
    assert '/static/playlist-editor.css?v=1' in html
    assert '/static/playlist-add-track.js?v=1' in html
    assert '/static/playlist-refine.js?v=1' in html


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


def test_description_and_remove_track_persist_from_playlist_page() -> None:
    script = _text("playlist-add-track.js")
    assert "descriptionInput.addEventListener('input'" in script
    assert "latest.description = descriptionInput.value.slice(0, 2000);" in script
    assert "async function persistPlaylist(playlist" in script
    assert "async function removeTrack(index)" in script
    assert "Remove track" in script
    assert "A playlist must contain at least one track." in script
    assert "playlist.tracks.splice(index, 1);" in script
    assert "await waitForExistingAutosave();" in script


def test_youtube_publish_reads_current_editor_state_at_publish_time() -> None:
    script = _text("youtube-publish.js")
    assert "function loadPlaylistFromSession()" in script
    assert "loadPlaylistFromSession();" in script
    assert "description: playlist.description || playlist.prompt || ''" in script
