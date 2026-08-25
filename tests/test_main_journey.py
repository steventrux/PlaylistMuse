import asyncio

import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
from backend.main import JourneyGenerateRequest
from backend.playlist_ordering import _local_chronological_order, _local_energy_order
from backend.youtube import track_identity_key


def _journey_request(**overrides) -> dict:
    payload = {
        "start": {
            "video_id": "start-vid",
            "title": "Start Song",
            "artists": "Start Artist",
            "album": "",
            "duration": "3:00",
            "thumbnail_url": "",
            "url": "https://music.youtube.com/watch?v=start-vid",
        },
        "end": {
            "video_id": "end-vid",
            "title": "End Song",
            "artists": "End Artist",
            "album": "",
            "duration": "3:00",
            "thumbnail_url": "",
            "url": "https://music.youtube.com/watch?v=end-vid",
        },
        "options": {
            "exclude_live": True,
            "exclude_covers": True,
            "exclude_remixes": True,
        },
    }
    payload.update(overrides)
    return payload


def test_journey_request_rejects_identical_start_and_end() -> None:
    payload = _journey_request(
        end={
            "video_id": "start-vid-alt",
            "title": "start song",
            "artists": "START ARTIST",
        }
    )
    # The model itself no longer validates this (see `_generate_from_journey_playlist`
    # below) so construction succeeds -- the identical-anchor check now happens at the
    # start of the generation function, before any Last.fm fetch or AI call, so both the
    # plain and streaming endpoints get a plain-string 400 (via the ValueError -> 400
    # HTTPException mapping) instead of Pydantic's list-shaped 422.
    request = JourneyGenerateRequest(**payload)

    with pytest.raises(ValueError, match="different tracks"):
        asyncio.run(main_module._generate_from_journey_playlist(request))


def test_generate_from_journey_endpoint_rejects_identical_anchors_with_plain_400() -> None:
    client = TestClient(main_module.app)
    payload = _journey_request(
        end={
            "video_id": "start-vid-alt",
            "title": "start song",
            "artists": "START ARTIST",
        }
    )

    response = client.post("/api/playlists/generate-from-journey", json=payload)

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert "different tracks" in detail


def test_journey_request_accepts_different_start_and_end() -> None:
    request = JourneyGenerateRequest(**_journey_request())
    assert not hasattr(request, "track_count")
    assert request.start.title == "Start Song"
    assert request.end.title == "End Song"


def test_generate_from_journey_playlist_pins_anchors_and_merges_evidence(monkeypatch) -> None:
    async def fake_similar(artist, title, *, limit, broaden=False, api_key=None, client=None):
        if artist == "Start Artist":
            return [
                {
                    "artist": "Shared Artist",
                    "title": "Shared Song",
                    "lastfm_strategy": "similar_track",
                }
            ]
        return [
            {
                "artist": "Shared Artist",
                "title": "Shared Song",
                "lastfm_strategy": "similar_track",
            },
            {
                "artist": "End Neighbor",
                "title": "End Neighbor Song",
                "lastfm_strategy": "similar_track",
            },
        ]

    captured_anchors = []

    async def fake_generate(prompt, count, options, *, allow_shortfall=False):
        captured_anchors.append(main_module._SEED_ANCHORS.get())
        assert count == 3
        assert "Start Song" in prompt
        assert "End Song" in prompt
        return {
            "title": "Journey",
            "description": "A path.",
            "tracks": [
                {
                    "artist": "Bridge Artist",
                    "title": "Bridge One",
                    "description": "d",
                    "reason": "r",
                },
                {
                    "artist": "Bridge Artist",
                    "title": "Bridge Two",
                    "description": "d",
                    "reason": "r",
                },
                {
                    "artist": "Bridge Artist",
                    "title": "Bridge Three",
                    "description": "d",
                    "reason": "r",
                },
            ],
        }

    monkeypatch.setattr(main_module, "JOURNEY_MAX_TRACKS", 5)
    monkeypatch.setattr(main_module, "similar_track_candidates", fake_similar)
    monkeypatch.setattr(main_module, "_generate", fake_generate)

    request = main_module.JourneyGenerateRequest(**_journey_request())
    result = asyncio.run(main_module._generate_from_journey_playlist(request))

    assert result["tracks"][0]["video_id"] == "start-vid"
    assert result["tracks"][-1]["video_id"] == "end-vid"
    assert len(result["tracks"]) == 5
    assert len(captured_anchors[0]) == 2


def test_generate_from_journey_playlist_degrades_gracefully_without_lastfm(monkeypatch) -> None:
    async def fake_similar(artist, title, *, limit, broaden=False, api_key=None, client=None):
        return []

    async def fake_generate(prompt, count, options, *, allow_shortfall=False):
        return {
            "title": "Journey",
            "description": "A path.",
            "tracks": [
                {
                    "artist": "Bridge Artist",
                    "title": "Bridge One",
                    "description": "d",
                    "reason": "r",
                },
                {
                    "artist": "Bridge Artist",
                    "title": "Bridge Two",
                    "description": "d",
                    "reason": "r",
                },
                {
                    "artist": "Bridge Artist",
                    "title": "Bridge Three",
                    "description": "d",
                    "reason": "r",
                },
            ],
        }

    monkeypatch.setattr(main_module, "similar_track_candidates", fake_similar)
    monkeypatch.setattr(main_module, "_generate", fake_generate)

    request = main_module.JourneyGenerateRequest(**_journey_request())
    result = asyncio.run(main_module._generate_from_journey_playlist(request))

    assert len(result["tracks"]) == 5


def _journey_track_payload(video_id: str, title: str, artists: str) -> dict:
    return {
        "video_id": video_id,
        "title": title,
        "artists": artists,
        "album": "",
        "duration": "3:00",
        "thumbnail_url": "",
        "url": f"https://music.youtube.com/watch?v={video_id}",
        "description": "d",
        "reason": "r",
    }


def test_journey_generation_retries_when_either_anchor_is_reproduced(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_generate(prompt, count, options, *, allow_shortfall=False):
        calls.append(prompt)
        assert count == 3
        if len(calls) == 1:
            tracks = [
                _journey_track_payload("alt-end", "End Song", "End Artist"),
                _journey_track_payload("t2", "Bridge Two", "Bridge Artist"),
                _journey_track_payload("t3", "Bridge Three", "Bridge Artist"),
            ]
        else:
            assert "Do not include" in prompt
            tracks = [
                _journey_track_payload("t2", "Bridge Two", "Bridge Artist"),
                _journey_track_payload("t3", "Bridge Three", "Bridge Artist"),
                _journey_track_payload("t4", "Bridge Four", "Bridge Artist"),
            ]
        return {"title": "Journey", "description": "A path.", "tracks": tracks}

    monkeypatch.setattr(main_module, "JOURNEY_MAX_TRACKS", 5)
    monkeypatch.setattr(main_module, "_generate", fake_generate)
    client = TestClient(main_module.app)
    response = client.post("/api/playlists/generate-from-journey", json=_journey_request())

    assert response.status_code == 200
    tracks = response.json()["tracks"]
    identities = [track_identity_key(t["title"], t["artists"]) for t in tracks]

    assert len(calls) == 2
    assert tracks[0]["video_id"] == "start-vid"
    assert tracks[-1]["video_id"] == "end-vid"
    assert identities.count(track_identity_key("End Song", "End Artist")) == 1
    assert len(identities) == len(set(identities))
    assert len(tracks) == 5


def test_journey_generation_drops_anchor_duplicate_when_it_keeps_being_reproduced(
    monkeypatch,
) -> None:
    # Observed in production: some models restate the start/end song among their own
    # suggestions despite the explicit exclusion instruction, even after the retry
    # re-states it. Journey tolerates a shorter result (allow_shortfall=True), so this
    # must degrade gracefully -- drop the duplicate and keep going -- rather than fail
    # the whole generation after a model quirk that a third attempt is unlikely to fix.
    calls: list[str] = []

    async def fake_generate(prompt, count, options, *, allow_shortfall=False):
        calls.append(prompt)
        tracks = [
            _journey_track_payload("alt-start", "Start Song", "Start Artist"),
            _journey_track_payload("t2", "Bridge Two", "Bridge Artist"),
            _journey_track_payload("t3", "Bridge Three", "Bridge Artist"),
        ]
        return {"title": "Journey", "description": "A path.", "tracks": tracks}

    monkeypatch.setattr(main_module, "_generate", fake_generate)
    client = TestClient(main_module.app)
    response = client.post("/api/playlists/generate-from-journey", json=_journey_request())

    assert response.status_code == 200
    payload = response.json()
    tracks = payload["tracks"]
    identities = [track_identity_key(t["title"], t["artists"]) for t in tracks]

    assert len(calls) == 2
    assert tracks[0]["video_id"] == "start-vid"
    assert tracks[-1]["video_id"] == "end-vid"
    # The duplicate ("alt-start", same identity as the start anchor) is dropped; only
    # the two genuinely distinct bridge tracks remain, plus both real anchors.
    assert identities.count(track_identity_key("Start Song", "Start Artist")) == 1
    assert {t["video_id"] for t in tracks} == {"start-vid", "t2", "t3", "end-vid"}
    assert payload["resolved_count"] == len(tracks)


def test_merge_journey_evidence_interleaves_and_preserves_both_sides_after_truncation() -> None:
    cap = main_module.MAX_LASTFM_CONTEXT_TRACKS
    start_evidence = [
        {
            "artist": f"Start Artist {i}",
            "title": f"Start Song {i}",
            "lastfm_strategy": "similar_track",
        }
        for i in range(cap)
    ]
    end_evidence = [
        {
            "artist": f"End Artist {i}",
            "title": f"End Song {i}",
            "lastfm_strategy": "similar_track",
        }
        for i in range(cap)
    ]

    # Confirm the premise the fix addresses: a naive concatenation truncated to the
    # eventual `_seed_evidence_guidance` cap would contain zero end-side evidence.
    naive_concat = [*start_evidence, *end_evidence][:cap]
    assert all(candidate["artist"].startswith("Start") for candidate in naive_concat)

    merged = main_module._merge_journey_evidence(start_evidence, end_evidence)
    truncated = merged[:cap]

    start_count = sum(1 for c in truncated if c["artist"].startswith("Start"))
    end_count = sum(1 for c in truncated if c["artist"].startswith("End"))

    assert start_count > 0
    assert end_count > 0
    assert abs(start_count - end_count) <= 1


def test_generate_from_journey_playlist_passes_balanced_evidence_into_the_prompt(
    monkeypatch,
) -> None:
    """End-to-end check that both anchors' evidence survives into the initial prompt."""
    cap = main_module.MAX_LASTFM_CONTEXT_TRACKS

    async def fake_similar(artist, title, *, limit, broaden=False, api_key=None, client=None):
        assert limit == cap // 2
        if artist == "Start Artist":
            return [
                {
                    "artist": f"Start Neighbor {i}",
                    "title": f"Start Neighbor Song {i}",
                    "lastfm_strategy": "similar_track",
                }
                for i in range(limit)
            ]
        return [
            {
                "artist": f"End Neighbor {i}",
                "title": f"End Neighbor Song {i}",
                "lastfm_strategy": "similar_track",
            }
            for i in range(limit)
        ]

    captured_prompts: list[str] = []
    captured_lastfm_candidates: list[tuple] = []

    async def fake_generate(prompt, count, options, *, allow_shortfall=False):
        captured_prompts.append(prompt)
        captured_lastfm_candidates.append(main_module._SEED_RECOMMENDATIONS.get())
        return {
            "title": "Journey",
            "description": "A path.",
            "tracks": [
                {
                    "artist": "Bridge Artist",
                    "title": "Bridge One",
                    "description": "d",
                    "reason": "r",
                },
                {
                    "artist": "Bridge Artist",
                    "title": "Bridge Two",
                    "description": "d",
                    "reason": "r",
                },
                {
                    "artist": "Bridge Artist",
                    "title": "Bridge Three",
                    "description": "d",
                    "reason": "r",
                },
            ],
        }

    monkeypatch.setattr(main_module, "similar_track_candidates", fake_similar)
    monkeypatch.setattr(main_module, "_generate", fake_generate)

    request = main_module.JourneyGenerateRequest(**_journey_request())
    asyncio.run(main_module._generate_from_journey_playlist(request))

    assert captured_prompts
    assert captured_lastfm_candidates
    lastfm_candidates = list(captured_lastfm_candidates[0])
    guidance = main_module._seed_evidence_guidance(lastfm_candidates, seed_mode="")
    assert "Start Neighbor" in guidance
    assert "End Neighbor" in guidance


def test_journey_instruction_does_not_read_as_an_energy_or_chronological_order_request() -> None:
    """Locks in the safety property established by rewording `_journey_instruction`.

    A downstream LLM-based constraint-interpretation pass could classify a journey
    prompt as requesting an explicit energy or chronological ordering, which would
    trigger a post-resolution reordering pass and scramble the carefully constructed
    bridge sequence. The deterministic local fallbacks used here are a fast, CI-safe
    proxy confirming the wording doesn't contain the vocabulary that would trip either
    classifier.
    """
    pairs = [
        (
            main_module.SeedTrack(
                video_id="vid-s1", title="Blast Beat Symphony", artists="Extreme Outfit"
            ),
            main_module.SeedTrack(
                video_id="vid-e1", title="Quiet Piano Trio", artists="Jazz Ensemble"
            ),
        ),
        (
            main_module.SeedTrack(
                video_id="vid-s2", title="Neon Dancefloor", artists="French House Act"
            ),
            main_module.SeedTrack(
                video_id="vid-e2", title="Porch Song", artists="Acoustic Folk Duo"
            ),
        ),
    ]
    for start, end in pairs:
        instruction = main_module._journey_instruction(start, end, bridge_count=5)
        assert _local_energy_order(instruction) is None
        assert _local_chronological_order(instruction) is None
