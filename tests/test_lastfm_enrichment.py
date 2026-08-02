from __future__ import annotations

import asyncio
from types import SimpleNamespace

from backend.lastfm_enrichment import enrich_lastfm_candidates
import backend.youtube as youtube_module


def _candidate() -> dict[str, str]:
    return {
        "artist": "Tredici Pietro",
        "title": "uomo che cade",
        "description": (
            "A data-backed recommendation associated with the reference track by "
            "Last.fm listeners."
        ),
        "reason": (
            "It broadens the playlist with a listening-pattern match while preserving "
            "the seed track's musical direction."
        ),
        "source": "lastfm",
    }


def test_lastfm_candidate_receives_ai_editorial_copy() -> None:
    async def fake_generator(config, prompt, count):
        assert config.configured is True
        assert "Ditonellapiaga" in prompt
        assert "Tredici Pietro — uomo che cade" in prompt
        assert count == 1
        return {
            "title": "Ignored",
            "description": "Ignored",
            "tracks": [
                {
                    "artist": "Tredici Pietro",
                    "title": "uomo che cade",
                    "description": (
                        "Airy synths and a suspended vocal line give the track a fragile, "
                        "weightless pull."
                    ),
                    "reason": (
                        "Its introspective glide cools the playlist after brighter pop "
                        "moments without losing the modern electronic thread."
                    ),
                }
            ],
        }

    enriched = asyncio.run(
        enrich_lastfm_candidates(
            "Ditonellapiaga",
            "Che fastidio!",
            [_candidate()],
            config=SimpleNamespace(configured=True),
            generator=fake_generator,
        )
    )

    assert enriched[0]["source"] == "lastfm"
    assert enriched[0]["description"].startswith("Airy synths")
    assert enriched[0]["reason"].startswith("Its introspective glide")
    assert "Last.fm listeners" not in enriched[0]["description"]


def test_lastfm_candidate_keeps_fallback_copy_when_ai_fails() -> None:
    async def failing_generator(config, prompt, count):
        raise RuntimeError("provider unavailable")

    original = _candidate()
    enriched = asyncio.run(
        enrich_lastfm_candidates(
            "Ditonellapiaga",
            "Che fastidio!",
            [original],
            config=SimpleNamespace(configured=True),
            generator=failing_generator,
        )
    )

    assert enriched[0]["description"] == original["description"]
    assert enriched[0]["reason"] == original["reason"]
    assert enriched[0]["source"] == "lastfm"


def test_youtube_resolution_preserves_lastfm_source(monkeypatch) -> None:
    class FakeClient:
        def search(self, query, filter, limit):
            return [
                {
                    "videoId": "video-1",
                    "title": "uomo che cade",
                    "artists": [{"name": "Tredici Pietro"}],
                    "album": {"name": "NON GUARDARE GIÙ"},
                    "duration": "3:38",
                    "thumbnails": [],
                }
            ]

    monkeypatch.setattr(youtube_module, "_client", lambda: FakeClient())

    track = youtube_module._resolve_one(
        _candidate(),
        {
            "exclude_live": True,
            "exclude_covers": True,
            "exclude_remixes": True,
        },
    )

    assert track is not None
    assert track["source"] == "lastfm"
