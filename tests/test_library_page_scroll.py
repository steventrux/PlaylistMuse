from pathlib import Path


def test_library_pagination_scrolls_to_page_top() -> None:
    source = Path('frontend/library.js').read_text()
    assert "window.scrollTo({top: 0, left: 0});" in source
    assert "$('library-list').scrollIntoView({block: 'start'});" not in source
