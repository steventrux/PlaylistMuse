from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_prompt_placeholder_is_generated_from_random_prompt_engine() -> None:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    surprise = (FRONTEND / "prompt-surprise.js").read_text(encoding="utf-8")

    old_placeholder = (
        "A slow-burning road-trip playlist with blues rock, warm guitars and "
        "a steady night-drive mood..."
    )
    assert old_placeholder not in html
    assert '<textarea id="prompt" maxlength="1950" rows="5"></textarea>' in html
    assert "const example = buildPrompt('example');" in surprise
    assert "prompt.placeholder = example;" in surprise
    assert "♪" not in surprise
    assert "♫" not in surprise
    assert "♬" not in surprise


def test_generation_controls_start_hidden_and_keep_status_outside() -> None:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")

    assert '<div id="generation-controls" class="hidden">' in html
    controls_start = html.index('<div id="generation-controls" class="hidden">')
    controls_end = html.index('<p id="status"', controls_start)
    controls = html[controls_start:controls_end]

    assert 'id="track-count"' in controls
    assert 'id="exclude-live"' in controls
    assert 'id="exclude-covers"' in controls
    assert 'id="exclude-remixes"' in controls
    assert 'id="ai-generation-warning"' in controls
    assert 'id="generate"' in controls
    assert 'id="status"' not in controls


def test_generation_feedback_stays_outside_prompt_shell() -> None:
    script = (FRONTEND / "generation-state.js").read_text(encoding="utf-8")

    assert "const promptShell = prompt?.closest('.prompt-input-shell');" in script
    assert "(promptShell || prompt).insertAdjacentElement('afterend', status);" in script
    assert "prompt.insertAdjacentElement('afterend', status);" not in script


def test_prompt_and_seed_control_generation_visibility() -> None:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    script = (FRONTEND / "app.js").read_text(encoding="utf-8")

    assert '/static/generation-state.js?v=3' in html
    assert '/static/app.js?v=20' in html
    assert "const generationState = window.PlaylistMuseGenerationState" in script
    assert "function updateGenerationControls()" in script
    assert "generationState.isGenerationReady(" in script
    assert "$('generation-controls').classList.toggle('hidden', !ready)" in script
    assert "$('prompt').addEventListener('input', updateGenerationControls)" in script
    assert "state.selectedSeed = seed;" in script
    assert "function clearSelectedSeed(" in script
    assert script.count("updateGenerationControls();") >= 4
    assert "updateGenerationControls();\n  void showInitialSetupIfRequired();" in script


def test_generation_locks_request_controls_until_completion_or_error() -> None:
    script = (FRONTEND / "app.js").read_text(encoding="utf-8")

    assert "generating: false" in script
    assert "const GENERATION_LOCKED_CONTROL_IDS = [" in script
    for control_id in (
        "prompt",
        "track-count",
        "exclude-live",
        "exclude-covers",
        "exclude-remixes",
        "prompt-surprise",
        "seed-surprise",
    ):
        assert f"'{control_id}'" in script
    assert "function setGenerationInputsLocked(locked)" in script
    assert "control.disabled = locked;" in script
    assert "control.setAttribute('aria-disabled', String(locked));" in script
    assert "if (button.disabled) return;" in script
    assert "if (state.generating) return;" in script
    assert "setGenerationInputsLocked(true);" in script
    assert "setGenerationInputsLocked(false);\n      resetGeneratingButton();" in script


def test_seed_search_is_disabled_while_empty_or_searching() -> None:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    script = (FRONTEND / "app.js").read_text(encoding="utf-8")

    assert (
        'id="seed-search" class="secondary" type="button" disabled '
        'aria-disabled="true"'
    ) in html
    assert "seedSearching: false" in script
    assert "function updateSeedSearchAvailability()" in script
    assert "generationState.isSeedSearchEnabled(" in script
    assert "button.setAttribute('aria-disabled', String(!enabled))" in script
    assert "$('seed-query').addEventListener('input', updateSeedSearchAvailability)" in script
    assert "function setSeedSearching(searching)" in script
    assert "if (state.seedSearching) return;" in script
    assert "setSeedSearching(true);" in script
    assert "setSeedSearching(false);" in script


def test_seed_results_are_built_in_one_dom_update() -> None:
    script = (FRONTEND / "app.js").read_text(encoding="utf-8")

    assert "function createSeedResult(seed)" in script
    assert "const fragment = document.createDocumentFragment();" in script
    assert "results.forEach((seed) => fragment.append(createSeedResult(seed)))" in script
    assert "container.append(fragment)" in script


def test_repeated_dom_lookups_are_cached() -> None:
    script = (FRONTEND / "app.js").read_text(encoding="utf-8")

    assert "const elementCache = new Map();" in script
    assert "if (!elementCache.has(id))" in script
    assert "elementCache.set(id, document.getElementById(id))" in script
