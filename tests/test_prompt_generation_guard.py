from pathlib import Path

from backend.prompt_validation import _local_temporal_assessment
from backend.validation_fixes import effective_temporal_range


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_abbreviated_year_range_is_expanded_deterministically():
    assert effective_temporal_range("canzoni rock dal 70 al 90") == (1970, 1990)


def test_abbreviated_range_after_cutoff_is_impossible():
    assessment = _local_temporal_assessment(
        "canzoni rock dal 70 al 90, pubblicate dopo il 1999"
    )

    assert assessment is not None
    assert assessment.status == "impossible"
    assert "2000" in assessment.reasons[0]
    assert "1990" in assessment.reasons[0]


def test_prompt_validation_guard_is_loaded_after_app_listener_registration():
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    app = '<script src="/static/app.js?v=21"></script>'
    guard = '<script src="/static/prompt-validation-guard.js?v=3"></script>'
    complexity = '<script src="/static/prompt-complexity.js?v=9"></script>'

    assert app in html
    assert guard in html
    assert complexity in html
    assert "prompt-validation-guard.js?v=2" not in html
    assert "prompt-complexity.js?v=8" not in html
    assert html.index(app) < html.index(guard)


def test_prompt_validation_guard_blocks_impossible_status_before_generation():
    script = (FRONTEND / "prompt-validation-guard.js").read_text(encoding="utf-8")

    assert "event.stopImmediatePropagation()" in script
    assert "result.status === 'impossible'" in script
    assert "button.click()" in script
    assert "/api/playlists/validate-prompt" in script


def test_prompt_validation_guard_waits_for_filter_conflict_analysis():
    guard = (FRONTEND / "prompt-validation-guard.js").read_text(encoding="utf-8")
    complexity = (FRONTEND / "prompt-complexity.js").read_text(encoding="utf-8")

    assert "await window.PlaylistMusePromptComplexity?.ensureCurrentAnalysis?.();" in guard
    assert "const conflicts = filterConflicts();" in guard
    assert "renderFilterConflicts(conflicts);" in guard
    assert "ensureCurrentAnalysis: () => ensureCurrentAnalysisImpl()" in complexity


def test_prompt_feedback_is_inserted_after_shell_not_inside_textarea_shell():
    script = (FRONTEND / "prompt-validation-guard.js").read_text(encoding="utf-8")

    assert "const shell = prompt?.closest('.prompt-input-shell');" in script
    assert "(shell || prompt)?.insertAdjacentElement('afterend', node);" in script
    assert "document.getElementById('prompt')?.insertAdjacentElement('afterend', node);" not in script


def test_prompt_filter_warning_uses_same_feedback_position():
    script = (FRONTEND / "prompt-complexity.js").read_text(encoding="utf-8")

    assert "const shell = prompt?.closest('.prompt-input-shell');" in script
    assert "(shell || prompt).insertAdjacentElement('afterend', node);" in script
    assert "controls.insertBefore(node, aiWarning)" not in script


def test_prompt_filter_conflict_does_not_duplicate_validation_alert():
    script = (FRONTEND / "prompt-validation-guard.js").read_text(encoding="utf-8")

    assert "document.getElementById('prompt-filter-conflict-warning')" in script
    assert "!visibleConflict.classList.contains('hidden')" in script
    assert "render({status: 'valid'});" in script
