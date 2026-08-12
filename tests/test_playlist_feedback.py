from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
ISSUE_TEMPLATE = ROOT / ".github" / "ISSUE_TEMPLATE" / "playlist_feedback.yml"
BUG_TEMPLATE = ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_playlist_feedback_is_separate_from_bug_reports() -> None:
    template = _text(ISSUE_TEMPLATE)
    bug_template = _text(BUG_TEMPLATE)

    assert "name: Playlist result feedback" in template
    assert 'title: "[Playlist feedback] "' in template
    assert 'labels: ["playlist feedback"]' in template
    assert "did not match your request" in template
    assert "separate from a **Bug report**" in template
    assert 'labels: ["bug"]' in bug_template
    assert "Diagnostic report" not in template


def test_playlist_page_exposes_feedback_without_coupling_it_to_draft_editing() -> None:
    html = _text(FRONTEND / "playlist.html")

    assert 'id="playlist-feedback"' in html
    assert '>Give feedback</button>' in html
    assert '/static/playlist-feedback.js?v=1' in html
    draft_start = html.index('id="playlist-draft-actions"')
    draft_end = html.index('</div>', draft_start)
    feedback_position = html.index('id="playlist-feedback"')
    assert feedback_position > draft_end


def test_feedback_prefills_only_playlist_quality_context() -> None:
    script = _text(FRONTEND / "playlist-feedback.js")

    assert "https://github.com/steventrux/PlaylistMuse/issues/new" in script
    assert "const FEEDBACK_LABEL = 'playlist feedback';" in script
    assert "labels: FEEDBACK_LABEL" in script
    assert "[Playlist feedback]" in script
    assert "<!-- playlistmuse-feedback:v1 -->" in script
    assert "## What did not match your request?" in script
    assert "## What did you expect instead?" in script
    assert "## Captured request" in script
    assert "## Previous refinement context" in script
    assert "## Generation options" in script
    assert "## Playlist result" in script
    assert "Exclude live tracks" in script
    assert "Exclude covers" in script
    assert "Exclude remixes" in script
    assert "generationRequest?.refinements" in script
    assert "track?.artists || track?.artist" in script
    assert "JSON.stringify(generationRequest)" not in script
    assert "api_key" not in script.casefold()
    assert "token" not in script.casefold()
    assert "diagnostic" not in script.casefold()


def test_support_documents_feedback_as_quality_input_not_technical_bug() -> None:
    support = _text(ROOT / "SUPPORT.md")

    assert "**Playlist result feedback**" in support
    assert "does **not** need a diagnostic ZIP" in support
    assert "prompt-quality regression corpus" in support
