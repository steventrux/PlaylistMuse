from __future__ import annotations

import asyncio

from backend import creative_intent
from backend.creative_intent import CreativeConflict, CreativeIntent


def _track(artist: str = "Test Artist", title: str = "Marginal Track"):
    return {"artist": artist, "title": title}


def test_rejected_track_is_not_re_evaluated_within_generation(monkeypatch) -> None:
    calls: list[list[str]] = []

    async def fake_fresh(config, tracks, *, intent=None):
        calls.append([track["title"] for track in tracks])
        if len(calls) == 1:
            return [CreativeConflict(1, 0.60, "Marginal creative fit.")]
        return []

    monkeypatch.setattr(creative_intent, "_assess_creative_fit_fresh", fake_fresh)

    async def scenario():
        creative_intent.activate_creative_intent(CreativeIntent())
        first = await creative_intent.assess_creative_fit(object(), [_track()])
        second = await creative_intent.assess_creative_fit(
            object(),
            [_track(" TEST ARTIST ", " marginal track "), _track("Other", "Fresh")],
        )
        return first, second

    first, second = asyncio.run(scenario())

    assert [item.index for item in first] == [1]
    assert [item.index for item in second] == [1]
    assert calls == [["Marginal Track"], ["Fresh"]]


def test_rejection_identity_includes_artist(monkeypatch) -> None:
    calls = 0

    async def fake_fresh(config, tracks, *, intent=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return [CreativeConflict(1, 0.60, "Marginal creative fit.")]
        return []

    monkeypatch.setattr(creative_intent, "_assess_creative_fit_fresh", fake_fresh)

    async def scenario():
        creative_intent.activate_creative_intent(CreativeIntent())
        await creative_intent.assess_creative_fit(
            object(), [_track("Artist One", "Shared Title")]
        )
        return await creative_intent.assess_creative_fit(
            object(), [_track("Artist Two", "Shared Title")]
        )

    result = asyncio.run(scenario())

    assert result == []
    assert calls == 2


def test_new_generation_reset_allows_fresh_evaluation(monkeypatch) -> None:
    calls = 0

    async def fake_fresh(config, tracks, *, intent=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return [CreativeConflict(1, 0.60, "Marginal creative fit.")]
        return []

    monkeypatch.setattr(creative_intent, "_assess_creative_fit_fresh", fake_fresh)

    async def scenario():
        creative_intent.activate_creative_intent(CreativeIntent())
        await creative_intent.assess_creative_fit(object(), [_track()])
        creative_intent.activate_creative_intent(CreativeIntent())
        return await creative_intent.assess_creative_fit(object(), [_track()])

    result = asyncio.run(scenario())

    assert result == []
    assert calls == 2


def test_explicit_intent_bypasses_generation_memory(monkeypatch) -> None:
    calls = 0

    async def fake_fresh(config, tracks, *, intent=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return [CreativeConflict(1, 0.60, "Marginal creative fit.")]
        assert intent is not None
        return []

    monkeypatch.setattr(creative_intent, "_assess_creative_fit_fresh", fake_fresh)

    async def scenario():
        creative_intent.activate_creative_intent(CreativeIntent())
        await creative_intent.assess_creative_fit(object(), [_track()])
        return await creative_intent.assess_creative_fit(
            object(),
            [_track()],
            intent=CreativeIntent(("requested atmosphere",), 0.95),
        )

    result = asyncio.run(scenario())

    assert result == []
    assert calls == 2
