from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def _read(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_ai_settings_show_only_primary_model_and_hide_fallback_controls() -> None:
    settings = _read("ai-settings.js")
    style = _read("ai-settings.css")

    assert "Model in use" in settings
    assert "function ensureModelControls()" in settings
    assert "fallbackRow.hidden = true" in settings
    assert "#fallback-row" in style
    assert "display: none !important" in style


def test_active_ai_summary_shows_primary_model_only() -> None:
    settings = _read("ai-settings.js")

    assert "function modelChain" not in settings
    assert "profile.fallback_1" not in settings.split(
        "function renderActiveProviderStatus()", 1
    )[1].split("function renderSelectedProviderStatus()", 1)[0]
    assert "profile.model ? ` · ${profile.model}`" in settings


def test_available_models_are_loaded_from_provider_api() -> None:
    settings = _read("ai-settings.js")
    routes = (ROOT / "backend/youtube_routes.py").read_text(encoding="utf-8")

    assert "fetch('/api/ai/models'" in settings
    assert "Refresh available models" in settings
    assert "compatible models reported by this API" in settings
    assert "Select a model reported as available by this API" in settings
    assert '@router.post("/ai/models"' in routes


def test_fixed_provider_hides_model_refresh_action() -> None:
    settings = _read("ai-settings.js")
    style = _read("ai-settings.css")

    assert "const openRouter = provider === 'openrouter_auto'" in settings
    assert "$('ai-model').readOnly = openRouter" in settings
    assert "if (data.fixed && models[0])" in settings
    assert "$('ai-model').readOnly = true" in settings
    assert ".settings-fields:has(#ai-model[readonly]) .ai-model-actions" in style
    assert "display: none" in style


def test_hidden_fallbacks_remain_saved_and_reconciled() -> None:
    settings = _read("ai-settings.js")

    assert "function reconcileHiddenFallbacks" in settings
    assert "fallback_1: $('ai-fallback-1').value.trim()" in settings
    assert "fallback_2: $('ai-fallback-2').value.trim()" in settings
    assert "defaults.fallback1" in settings
    assert "defaults.fallback2" in settings
