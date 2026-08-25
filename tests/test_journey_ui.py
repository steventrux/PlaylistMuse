from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_journey_tab_and_picker_markup_exist() -> None:
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")

    assert '<button class="mode" data-mode="journey" type="button">From Journey</button>' in html
    assert 'id="journey-start-query"' in html
    assert 'id="journey-end-query"' in html
    assert 'id="track-count-field"' in html


def test_app_js_wires_journey_endpoint_and_short_bridge_confirmation() -> None:
    script = (FRONTEND / "app.js").read_text(encoding="utf-8")

    assert "endpoint = '/api/playlists/generate-from-journey/stream';" in script
    assert "state.mode === 'journey' && data.tracks.length - 2 < 3" in script


def test_replacement_history_regex_covers_journey_stream_endpoint() -> None:
    script = (FRONTEND / "replacement-history.js").read_text(encoding="utf-8")

    assert (
        "/\\/api\\/playlists\\/generate(?:-from-(?:seed|journey))?(?:\\/stream)?(?:\\?|$)/"
        in script
    )


def test_playlist_feedback_has_journey_flow_label() -> None:
    script = (FRONTEND / "playlist-feedback.js").read_text(encoding="utf-8")

    assert "if (generationRequest?.mode === 'journey') return 'Track-to-track journey generation';" in script
