from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def _text(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_library_pagination_uses_icon_boundary_controls_with_tooltips() -> None:
    html = _text("library.html")

    assert '/static/library-pagination.css?v=1' in html
    assert '/static/library-pagination.js?v=2' in html
    assert '/static/library.js?v=12' in html

    for control_id, tooltip in (
        ('library-page-first', 'Go to first page'),
        ('library-page-previous', 'Go to previous page'),
        ('library-page-next', 'Go to next page'),
        ('library-page-last', 'Go to last page'),
    ):
        assert f'id="{control_id}"' in html
        assert f'aria-label="{tooltip}"' in html
        assert f'title="{tooltip}"' in html

    assert '>Previous</button>' not in html
    assert '>Next</button>' not in html


def test_library_pagination_uses_five_desktop_and_three_mobile_page_numbers() -> None:
    script = _text("library.js")
    pagination = _text("library-pagination.js")

    assert "window.matchMedia('(max-width: 650px)')" in script
    assert "return MOBILE_PAGINATION.matches ? 3 : paginationTools.DEFAULT_VISIBLE_PAGES;" in script
    assert "DEFAULT_VISIBLE_PAGES = 5" in pagination
    assert ".pageTokens(currentPage, pageState.totalPages, visiblePageNumberCount())" in script
    assert "$('library-page-first').disabled = atFirstPage;" in script
    assert "$('library-page-last').disabled = atLastPage;" in script
    assert "$('library-page-first').addEventListener('click', () => setLibraryPage(1));" in script
    assert "setLibraryPage(Number.MAX_SAFE_INTEGER)" in script


def test_library_pagination_icon_controls_remain_compact_on_mobile() -> None:
    style = _text("library-pagination.css")

    assert ".library-page-nav svg" in style
    assert "width: 34px" in style
    assert "min-width: 34px" in style
    assert "@media (max-width: 650px)" in style
    assert ".library-pagination,\n  .library-page-numbers" in style
    assert "gap: 4px" in style
