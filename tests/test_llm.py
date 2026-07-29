"""Regression tests for provider-neutral LLM helpers."""

from __future__ import annotations

import json

from backend import llm


def _track(artist: str, title: str) -> dict[str, str]:
    return {
        "artist": artist,
        "title": title,
        "description": "A concise musical description.",
        "reason": "It supports the requested playlist flow.",
    }


def test_extract_json_accepts_fenced_payload() -> None:
    source = {
        "title": "Night Drive",
        "description": "A focused late-night rock sequence.",
        "tracks": [_track("The Rolling Stones", "Gimme Shelter")],
    }

    result = llm._extract_json(f"```json\n{json.dumps(source)}\n```")

    assert result == source


def test_extract_json_ignores_incomplete_tracks() -> None:
    source = {
        "title": "Night Drive",
        "description": "A focused late-night rock sequence.",
        "tracks": [
            _track("The Rolling Stones", "Gimme Shelter"),
            {"artist": "AC/DC", "title": "Back in Black"},
        ],
    }

    result = llm._extract_json(json.dumps(source))

    assert result["tracks"] == [_track("The Rolling Stones", "Gimme Shelter")]


def test_unique_tracks_ignores_case_accents_and_punctuation() -> None:
    candidates = [
        _track("Beyoncé", "Halo!"),
        _track("beyonce", "halo"),
        _track("AC/DC", "Back in Black"),
    ]

    result = llm._unique_tracks(candidates)

    assert result == [candidates[0], candidates[2]]


def test_safe_error_message_redacts_urls_and_credentials() -> None:
    error = ValueError(
        "Request failed at https://provider.example/v1?key=secret-value "
        "using sk-or-abcdefghijklmnop"
    )

    message = llm.safe_error_message(error)

    assert "https://" not in message
    assert "secret-value" not in message
    assert "sk-or-abcdefghijklmnop" not in message
    assert "[redacted]" in message
