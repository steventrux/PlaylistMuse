from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def _text(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_import_page_has_url_field_and_wires_shared_scripts() -> None:
    html = _text("import.html")

    assert '<label for="import-url">YouTube Music playlist link</label>' in html
    assert 'id="import-url"' in html
    assert 'id="import-url-submit"' in html
    assert 'id="import-url-guidance"' in html
    assert '<script src="/static/common.js?v=23"></script>' in html
    assert '<script src="/static/import-playlist.js?v=1"></script>' in html
    assert html.index('<script src="/static/common.js?v=23"></script>') < html.index(
        '<script src="/static/import-playlist.js?v=1"></script>'
    )


def test_import_page_guidance_is_an_alert_box_not_a_plain_hint() -> None:
    html = _text("import.html")
    style = _text("controls.css")
    script = _text("import-playlist.js")

    assert (
        '<div id="import-url-guidance" class="import-url-alert hidden" role="alert" '
        'aria-live="assertive"></div>'
    ) in html
    assert ".import-url-alert {" in style
    assert "background: var(--error-bg);" in style
    assert "guidance.classList.toggle('hidden', !text);" not in script


def test_import_url_label_has_spacing_margin_from_its_field() -> None:
    style = _text("controls.css")

    assert 'label[for="import-url"] {' in style
    rule_start = style.index('label[for="import-url"] {')
    rule_end = style.index("}", rule_start)
    rule = style[rule_start:rule_end]
    assert "margin-bottom: 12px;" in rule


def test_duplicate_import_error_links_to_the_existing_library_playlist() -> None:
    script = _text("import-playlist.js")
    style = _text("controls.css")

    assert "if (detail && typeof detail === 'object' && detail.playlist_id) {" in script
    assert "error.existingPlaylistId = detail.playlist_id;" in script
    assert "error.existingPlaylistName = detail.playlist_name;" in script
    assert "if (error.existingPlaylistId) {" in script
    assert "link.href = `/static/playlist.html?id=${encodeURIComponent(error.existingPlaylistId)}`;" in script
    assert "link.textContent = error.existingPlaylistName;" in script
    assert ".import-url-alert a {" in style

    # guidance is display:grid, so the message must be a single wrapped child --
    # appending text nodes and the link as direct siblings previously put each
    # on its own grid row instead of flowing as one inline sentence.
    assert "const message = document.createElement('p');" in script
    assert "guidance.append(message);" in script
    assert ".import-url-alert p {" in style


def test_import_playlist_script_calls_preview_endpoint_and_hands_off_to_playlist_page() -> None:
    script = _text("import-playlist.js")

    assert "/api/youtube/playlists/import-preview" in script
    assert "sessionStorage.setItem('playlistmuse-generated-playlist', JSON.stringify(data));" in script
    assert "sessionStorage.removeItem('playlistmuse-generation-request');" in script
    assert "window.location.assign('/static/playlist.html');" in script
    # Import must not trigger the AI taste-capture/feedback prompts meant for
    # generated playlists (see playlist-positive-feedback.js, playlist-feedback.js,
    # both gated on playlistmuseFreshlyGenerated).
    assert "playlistmuseFreshlyGenerated" not in script


def test_primary_navigation_lists_import_between_create_and_library() -> None:
    script = _text("common.js")

    create_index = script.index("page: 'create',")
    import_index = script.index("page: 'import',")
    library_index = script.index("page: 'library',")
    assert create_index < import_index < library_index

    assert "label: 'Import playlist'," in script
    assert "href: '/static/import.html'," in script
    assert "path.endsWith('/import.html')) return 'import';" in script
    assert "path.endsWith('/import.html')" in script.split("function primaryNavigationHost()")[1].split(
        "function ensurePrimaryNavigationStyles()"
    )[0]
