"""Protect the boundary between prompt text and playlist option selectors."""

from __future__ import annotations

import asyncio
from itertools import product
from typing import Any

import pytest

from backend.schemas import PlaylistOptions
from backend.services import playlist_generation


def _candidates() -> list[dict[str, str]]:
    return [
        {
            "artist": f"Artist {index}",
            "title": f"Song {index}",
            "description": f"Description {index}",
            "reason": f"Reason {index}",
        }
        for index in range(1, 6)
    ]


def _tracks() -> list[dict[str, Any]]:
    return [
        {
            "video_id": f"video-{index}",
            "title": f"Song {index}",
            "artists": f"Artist {index}",
            "description": f"Description {index}",
            "reason": f"Reason {index}",
        }
        for index in range(1, 6)
    ]


@pytest.mark.parametrize(
    ("exclude_live", "exclude_covers", "exclude_remixes"),
    list(product((False, True), repeat=3)),
)
def test_selectors_remain_structured_and_are_never_injected_into_prompt(
    exclude_live: bool,
    exclude_covers: bool,
    exclude_remixes: bool,
) -> None:
    prompt = "A nocturnal blues-rock drive through the Alps"
    options = PlaylistOptions(
        exclude_live=exclude_live,
        exclude_covers=exclude_covers,
        exclude_remixes=exclude_remixes,
    )
    expected_exclusions = options.model_dump()
    received_prompts: list[str] = []
    received_exclusions: list[dict[str, bool]] = []
    scheduled: list[tuple[list[dict[str, Any]], dict[str, bool]]] = []
    candidates = _candidates()
    tracks = _tracks()

    async def fake_draft(config: object, received_prompt: str, count: int):
        del config
        received_prompts.append(received_prompt)
        assert count == 5
        return {
            "title": "Selector Boundary",
            "description": "Options remain separate from prompt text.",
            "tracks": candidates,
        }

    async def fake_resolve(
        received_candidates: list[dict[str, Any]],
        exclusions: dict[str, bool],
    ):
        assert received_candidates == candidates
        received_exclusions.append(dict(exclusions))
        return tracks, []

    def fake_shadow_scheduler(
        final_tracks: list[dict[str, Any]],
        received_options: PlaylistOptions,
    ) -> None:
        scheduled.append((list(final_tracks), received_options.model_dump()))

    result = asyncio.run(
        playlist_generation.generate_playlist(
            prompt,
            5,
            options,
            load_config_fn=lambda: object(),
            generate_playlist_draft_fn=fake_draft,
            resolve_candidates_fn=fake_resolve,
            track_identity_key_fn=lambda title, artists: f"{artists}::{title}",
            shadow_scheduler_fn=fake_shadow_scheduler,
        )
    )

    assert received_prompts == [prompt]
    assert received_exclusions == [expected_exclusions]
    assert scheduled == [(tracks, expected_exclusions)]
    assert result["prompt"] == prompt
    assert "exclude_live" not in result["prompt"]
    assert "exclude_covers" not in result["prompt"]
    assert "exclude_remixes" not in result["prompt"]
