from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def _text(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_library_loads_refinement_assets_before_library_renderer() -> None:
    html = _text("library.html")

    assert '/static/library-refine.css?v=1' in html
    refine = '<script src="/static/library-refine.js?v=1"></script>'
    library = '<script src="/static/library.js?v=5"></script>'
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


def test_refinement_preview_is_compact_and_scrollable() -> None:
    style = _text("library-refine.css")

    assert ".library-refine-panel" in style
    assert ".library-refine-preview" in style
    assert "max-height: 280px;" in style
    assert "overflow: auto;" in style
    assert ".library-refine-actions" in style
