from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_prompt_placeholder_is_updated_without_music_note() -> None:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")

    placeholder = (
        "A slow-burning road-trip playlist with blues rock, warm guitars and "
        "a steady night-drive mood..."
    )
    assert f'placeholder="{placeholder}"' in html
    assert "A nocturnal blues-rock drive through the Alps" not in html
    assert "♪" not in placeholder
    assert "♫" not in placeholder
    assert "♬" not in placeholder


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


def test_prompt_and_seed_control_generation_visibility() -> None:
    script = (FRONTEND / "app.js").read_text(encoding="utf-8")

    assert "function updateGenerationControls()" in script
    assert "state.mode === 'prompt'" in script
    assert "Boolean(normalizedPrompt())" in script
    assert "Boolean(state.selectedSeed)" in script
    assert "$('generation-controls').classList.toggle('hidden', !ready)" in script
    assert "$('prompt').addEventListener('input', updateGenerationControls)" in script
    assert "state.selectedSeed = seed;" in script
    assert "state.selectedSeed = null;" in script
    assert script.count("updateGenerationControls();") >= 6
    assert "updateGenerationControls();\n  void showInitialSetupIfRequired();" in script


def test_seed_search_is_disabled_while_empty_or_searching() -> None:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    script = (FRONTEND / "app.js").read_text(encoding="utf-8")

    assert (
        'id="seed-search" class="secondary" type="button" disabled '
        'aria-disabled="true"'
    ) in html
    assert "seedSearching: false" in script
    assert "function updateSeedSearchAvailability()" in script
    assert "state.seedSearching || !$('seed-query').value.trim()" in script
    assert "button.setAttribute('aria-disabled', String(disabled))" in script
    assert "$('seed-query').addEventListener('input', updateSeedSearchAvailability)" in script
    assert "state.seedSearching = true" in script
    assert "state.seedSearching = false" in script
    assert script.count("updateSeedSearchAvailability();") >= 4
