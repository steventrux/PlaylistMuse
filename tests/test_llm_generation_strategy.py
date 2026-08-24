from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import backend.llm as llm


def _draft(start: int, count: int) -> str:
    return json.dumps(
        {
            "title": "Focused Journey",
            "description": "A coherent playlist with a deliberate musical arc.",
            "tracks": [
                {
                    "artist": f"Artist {index}",
                    "title": f"Track {index}",
                    "description": f"Sound of track {index}.",
                    "reason": f"Track {index} supports the requested flow.",
                }
                for index in range(start, start + count)
            ],
        }
    )


def test_system_prompt_uses_constraint_first_curation_protocol() -> None:
    assert "silently build a constraint checklist" in llm.SYSTEM_PROMPT
    assert "explicit mandatory constraints and placements" in llm.SYSTEM_PROMPT
    assert "ordering, alternation, sections, transitions or an energy progression" in llm.SYSTEM_PROMPT
    assert "Never relax a mandatory requirement" in llm.SYSTEM_PROMPT
    assert "Do not output this planning" in llm.SYSTEM_PROMPT


def test_system_prompt_forbids_track_counts_in_title_and_description() -> None:
    """Regression: two separate real generations stated a count that didn't match the
    final tracks array -- "five tracks by The Rolling Stones" when only 3 were present,
    then "A 23-track chronological descent" on a 20-track playlist. Trying to keep an
    LLM-stated count in sync with the finished array is unreliable; forbidding the count
    outright removes the failure mode instead of chasing it.
    """
    assert (
        'Never state a number of songs, tracks or artist tally in the title or the '
        'description' in llm.SYSTEM_PROMPT
    )
    assert (
        "neither the title nor the description states any number of songs, tracks or "
        "artist tally" in llm.SYSTEM_PROMPT
    )


def test_nearly_complete_response_fills_only_missing_tracks(monkeypatch) -> None:
    calls: list[tuple[int, bool]] = []

    async def fake_request_model(
        client,
        config,
        model,
        user_prompt,
        count,
        *,
        exact_count=False,
    ):
        calls.append((count, exact_count))
        if count == 10:
            return _draft(1, 8)
        assert count == 2
        return _draft(9, 2)

    monkeypatch.setattr(llm, "_request_model", fake_request_model)
    config = SimpleNamespace(
        configured=True,
        provider="openrouter_free",
        model_chain=("model-a",),
    )

    result = asyncio.run(llm.generate_playlist_draft(config, "Road trip rock", 10))

    assert len(result["tracks"]) == 10
    assert calls == [(10, True), (2, False)]


def test_sparse_partial_still_allows_full_retry(monkeypatch) -> None:
    calls = 0

    async def fake_request_model(
        client,
        config,
        model,
        user_prompt,
        count,
        *,
        exact_count=False,
    ):
        nonlocal calls
        calls += 1
        return _draft(1, 3 if calls == 1 else count)

    monkeypatch.setattr(llm, "_request_model", fake_request_model)
    config = SimpleNamespace(
        configured=True,
        provider="openrouter_free",
        model_chain=("model-a",),
    )

    result = asyncio.run(llm.generate_playlist_draft(config, "Road trip rock", 10))

    assert len(result["tracks"]) == 10
    assert calls == 2
