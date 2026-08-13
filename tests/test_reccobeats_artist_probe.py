from __future__ import annotations

import json
import time
import unicodedata

import httpx

CASES = [
    ("Takagi & Ketra", "Roma-Bangkok"),
    ("Boomdabash", "Karaoke"),
    ("Negramaro", "Estate"),
    ("Måneskin", "ZITTO E BUONI"),
    ("Club Dogo", "P.V.P."),
    ("Gabry Ponte", "Geordie"),
    ("Max Pezzali", "Hanno ucciso l'Uomo Ragno"),
]
BASE = "https://api.reccobeats.com/v1"


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return " ".join("".join(ch if ch.isalnum() else " " for ch in value).split())


def _content(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        value = payload.get("content", [])
        return value if isinstance(value, list) else []
    return []


def _get(client: httpx.Client, url: str, **kwargs) -> httpx.Response:
    response = client.get(url, **kwargs)
    for _ in range(3):
        if response.status_code != 429:
            return response
        try:
            wait = float(response.headers.get("Retry-After", "1"))
        except ValueError:
            wait = 1.0
        time.sleep(min(5.0, max(0.5, wait)))
        response = client.get(url, **kwargs)
    return response


def test_reccobeats_strict_artist_probe() -> None:
    rows = []
    with httpx.Client(timeout=15.0, headers={"Accept": "application/json", "User-Agent": "PlaylistMuse-ReccoBeats-Probe/1.0"}) as client:
        for artist, title in CASES:
            row = {"artist": artist, "title": title}
            response = _get(
                client,
                f"{BASE}/artist/search",
                params={"searchText": artist, "size": 20, "page": 0},
            )
            row["artist_search_status"] = response.status_code
            try:
                artists = _content(response.json()) if response.is_success else []
            except ValueError:
                artists = []
            exact_artist = next(
                (
                    item
                    for item in artists
                    if isinstance(item, dict) and _norm(str(item.get("name", ""))) == _norm(artist)
                ),
                None,
            )
            if not exact_artist or not exact_artist.get("id"):
                row["artist_found"] = False
                rows.append(row)
                continue
            row["artist_found"] = True
            row["artist_id"] = exact_artist["id"]

            found = None
            pages_checked = 0
            for page in range(6):
                tracks_response = _get(
                    client,
                    f"{BASE}/artist/{exact_artist['id']}/track",
                    params={"size": 100, "page": page},
                )
                pages_checked += 1
                row["tracks_status"] = tracks_response.status_code
                try:
                    tracks = _content(tracks_response.json()) if tracks_response.is_success else []
                except ValueError:
                    tracks = []
                for item in tracks:
                    if not isinstance(item, dict):
                        continue
                    candidate_title = str(item.get("trackTitle") or item.get("name") or item.get("title") or "")
                    if _norm(candidate_title) == _norm(title):
                        found = item
                        break
                if found or len(tracks) < 100:
                    break
                time.sleep(0.1)
            row["pages_checked"] = pages_checked
            if not found or not found.get("id"):
                row["track_found"] = False
                rows.append(row)
                continue

            row["track_found"] = True
            row["matched_title"] = found.get("trackTitle") or found.get("name") or found.get("title")
            row["reccobeats_id"] = found["id"]
            row["isrc"] = found.get("isrc")
            features = _get(client, f"{BASE}/track/{found['id']}/audio-features")
            row["features_status"] = features.status_code
            if features.is_success:
                try:
                    payload = features.json()
                except ValueError:
                    payload = {}
                if isinstance(payload, dict):
                    for key in ("danceability", "energy", "valence", "tempo", "liveness", "acousticness"):
                        if key in payload:
                            row[key] = payload[key]
            rows.append(row)
            time.sleep(0.1)

    print("RECCOBEATS_ARTIST_PROBE=" + json.dumps(rows, ensure_ascii=False, sort_keys=True))
    assert False, "intentional strict live probe; inspect RECCOBEATS_ARTIST_PROBE"
