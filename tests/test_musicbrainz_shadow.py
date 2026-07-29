"""Tests for the opt-in MusicBrainz shadow metadata path."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from typing import Any

from backend.metadata import musicbrainz
from backend.schemas import PlaylistOptions
from backend.services import musicbrainz_shadow
from backend.services import playlist_generation


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


def _track(index: int) -> dict[str, Any]:
    return {
        "video_id": f"video-{index}",
        "title": f"Song {index}",
        "artists": f"Artist {index}",
        "album": "Album",
        "duration": "4:15",
        "description": "Description",
        "reason": "Reason",
    }


def test_recording_query_uses_fielded_escaped_values() -> None:
    query = musicbrainz.build_recording_query('A "Quoted" Song', "AC/DC")

    assert query == 'recording:"A \\"Quoted\\" Song" AND artistname:"AC/DC"'


def test_musicbrainz_client_returns_canonical_metadata(monkeypatch) -> None:
    payload = {
        "recordings": [
            {
                "id": "recording-mbid",
                "score": "100",
                "title": "Back in Black",
                "length": 255000,
                "first-release-date": "1980-07-25",
                "artist-credit": [
                    {
                        "artist": {
                            "id": "artist-mbid",
                            "name": "AC/DC",
                        }
                    }
                ],
                "isrcs": [{"id": "AUAP08000046"}],
                "tags": [{"name": "hard rock", "count": 4}],
                "releases": [
                    {
                        "id": "release-mbid",
                        "title": "Back in Black",
                        "status": "Official",
                        "date": "1980-07-25",
                        "release-group": {
                            "id": "release-group-mbid",
                            "primary-type": "Album",
                            "first-release-date": "1980-07-25",
                        },
                    }
                ],
            }
        ]
    }

    async def fake_get(client: object, *, params: dict[str, Any]) -> FakeResponse:
        del client
        assert params["fmt"] == "json"
        assert params["limit"] == 25
        assert "Back in Black" in params["query"]
        return FakeResponse(payload)

    monkeypatch.setattr(musicbrainz, "_rate_limited_get", fake_get)
    client = musicbrainz.MusicBrainzClient(client=object())
    result = asyncio.run(
        client.search_track("Back in Black", "AC/DC", duration_ms=255000)
    )

    assert result is not None
    assert result["matched"] is True
    assert result["recording_mbid"] == "recording-mbid"
    assert result["artists"] == [{"name": "AC/DC", "mbid": "artist-mbid"}]
    assert result["isrcs"] == ["AUAP08000046"]
    assert result["tags"] == ["hard rock"]
    assert result["duration_delta_ms"] == 0
    assert result["release_mbid"] == "release-mbid"
    assert result["release_title"] == "Back in Black"
    assert result["release_group_primary_type"] == "Album"
    assert result["release_group_mbids"] == ["release-group-mbid"]


def test_musicbrainz_client_prefers_studio_version(monkeypatch) -> None:
    payload = {
        "recordings": [
            {
                "id": "live-recording",
                "score": "100",
                "title": "Gimme Shelter",
                "length": 364000,
                "first-release-date": "1991",
                "disambiguation": "live",
                "artist-credit": [
                    {"artist": {"id": "stones", "name": "The Rolling Stones"}}
                ],
                "releases": [
                    {
                        "id": "live-release",
                        "title": "Live USA",
                        "status": "Bootleg",
                        "date": "1991",
                        "release-group": {
                            "id": "live-group",
                            "primary-type": "Album",
                            "secondary-types": ["Live"],
                        },
                    }
                ],
            },
            {
                "id": "studio-recording",
                "score": "100",
                "title": "Gimme Shelter",
                "length": 271000,
                "first-release-date": "1969-12-05",
                "artist-credit": [
                    {"artist": {"id": "stones", "name": "The Rolling Stones"}}
                ],
                "releases": [
                    {
                        "id": "studio-release",
                        "title": "Let It Bleed",
                        "status": "Official",
                        "date": "1969-12-05",
                        "release-group": {
                            "id": "studio-group",
                            "primary-type": "Album",
                            "first-release-date": "1969-12-05",
                        },
                    }
                ],
            },
        ]
    }

    async def fake_get(client: object, *, params: dict[str, Any]) -> FakeResponse:
        del client, params
        return FakeResponse(payload)

    monkeypatch.setattr(musicbrainz, "_rate_limited_get", fake_get)
    client = musicbrainz.MusicBrainzClient(client=object())
    result = asyncio.run(
        client.search_track(
            "Gimme Shelter",
            "The Rolling Stones",
            duration_ms=271000,
        )
    )

    assert result is not None
    assert result["recording_mbid"] == "studio-recording"
    assert result["release_title"] == "Let It Bleed"
    assert result["duration_delta_ms"] == 0
    assert result["version_penalty"] == 0


def test_term_matching_does_not_treat_alive_as_live() -> None:
    assert musicbrainz._term_penalty(["The Sounds Alive Promotion Sampler"]) == 0
    assert musicbrainz._term_penalty(["Live at Wembley"]) == 35


def test_shadow_mode_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("PLAYLISTMUSE_MUSICBRAINZ_SHADOW", raising=False)

    assert musicbrainz_shadow.musicbrainz_shadow_enabled() is False
    assert musicbrainz_shadow.schedule_musicbrainz_shadow([_track(1)]) is False


def test_duration_parser_supports_track_durations() -> None:
    assert musicbrainz_shadow._duration_ms("4:15") == 255000
    assert musicbrainz_shadow._duration_ms("1:02:03") == 3723000
    assert musicbrainz_shadow._duration_ms("invalid") is None


def test_shadow_collector_writes_private_ndjson_without_mutating_tracks(tmp_path) -> None:
    tracks = [_track(1), _track(2)]
    original = deepcopy(tracks)
    output = tmp_path / "shadow.ndjson"

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback

        async def search_track(
            self,
            title: str,
            artists: str,
            *,
            duration_ms: int | None = None,
        ) -> dict[str, Any]:
            assert duration_ms == 255000
            return {
                "matched": True,
                "recording_mbid": f"mbid-{title}",
                "recording_title": title,
                "artists": [{"name": artists, "mbid": f"artist-{artists}"}],
            }

    payload = asyncio.run(
        musicbrainz_shadow.run_musicbrainz_shadow(
            tracks,
            client_factory=FakeClient,
            output_path=output,
            sample_size=2,
        )
    )

    assert tracks == original
    assert payload["track_count"] == 2
    assert payload["sampled_count"] == 2
    assert payload["matched_count"] == 2
    stored = json.loads(output.read_text(encoding="utf-8").strip())
    assert stored["results"][0]["input"] == {
        "video_id": "video-1",
        "title": "Song 1",
        "artists": "Artist 1",
        "duration": "4:15",
        "duration_ms": 255000,
    }
    assert stored["results"][0]["musicbrainz"]["recording_mbid"] == "mbid-Song 1"


def test_playlist_generation_schedules_shadow_after_final_tracks() -> None:
    tracks = [_track(index) for index in range(1, 6)]
    scheduled: list[list[dict[str, Any]]] = []

    async def fake_draft(config: object, prompt: str, count: int):
        del config, prompt, count
        return {
            "title": "Shadow Safe",
            "description": "The public response remains unchanged.",
            "tracks": [
                {
                    "artist": track["artists"],
                    "title": track["title"],
                    "description": track["description"],
                    "reason": track["reason"],
                }
                for track in tracks
            ],
        }

    async def fake_resolve(candidates: list[dict], exclusions: dict[str, bool]):
        del candidates, exclusions
        return tracks, []

    result = asyncio.run(
        playlist_generation.generate_playlist(
            "Classic rock",
            5,
            PlaylistOptions(),
            load_config_fn=lambda: object(),
            generate_playlist_draft_fn=fake_draft,
            resolve_candidates_fn=fake_resolve,
            track_identity_key_fn=lambda title, artists: f"{artists}::{title}",
            shadow_scheduler_fn=lambda final: scheduled.append(deepcopy(final)),
        )
    )

    assert result["tracks"] == tracks
    assert scheduled == [tracks]
