from __future__ import annotations

import backend.youtube as youtube


class _SearchClient:
    def search(self, query, filter=None, limit=None):
        return [
            {
                "videoId": "feature-credit-1",
                "title": "Roma - Bangkok (feat. Lali)",
                "artists": [{"name": "Baby K"}],
                "album": {"name": "Kiss Kiss Bang Bang"},
            }
        ]


def test_title_matching_ignores_trailing_feature_credit() -> None:
    assert youtube._title_score("Roma-Bangkok", "Roma - Bangkok (feat. Lali)") == 100.0
    assert youtube._title_score("Song", "Song ft. Guest") == 100.0
    assert youtube._title_score("Song", "Song (featuring Guest)") == 100.0


def test_title_matching_keeps_normal_with_titles() -> None:
    assert youtube._title_score("With or Without You", "With or Without You") == 100.0


def test_resolver_accepts_catalogue_feature_credit(monkeypatch) -> None:
    monkeypatch.setattr(
        youtube,
        "_read_youtube_cache_entry",
        lambda *args, **kwargs: (False, None, None),
    )
    monkeypatch.setattr(youtube, "_write_youtube_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(youtube, "_thread_client", lambda: _SearchClient())

    track, diagnostic = youtube._resolve_one_with_diagnostic(
        {"artist": "Baby K", "title": "Roma-Bangkok"},
        {
            "exclude_live": True,
            "exclude_covers": True,
            "exclude_remixes": True,
        },
    )

    assert diagnostic is None
    assert track is not None
    assert track["match_score"] == 100.0
