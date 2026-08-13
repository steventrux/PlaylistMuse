from __future__ import annotations

import json
import time
import unicodedata

import httpx


TRACKS = [
    ("Paola & Chiara", "Vamos a bailar (Esta vida nueva)", "fit", 0.90),
    ("Takagi & Ketra", "Roma-Bangkok", "fit", 0.90),
    ("Baby K", "Da zero a cento", "fit", 0.90),
    ("The Kolors", "Italodisco", "fit", 0.95),
    ("Annalisa", "Mon Amour", "fit", 0.90),
    ("Rocco Hunt", "A Un Passo Dalla Luna", "fit", 0.90),
    ("Boomdabash", "Karaoke", "fit", 0.90),
    ("Fred De Palma", "Una volta ancora", "fit", 0.90),
    ("J-Ax", "Ostia Lido", "fit", 0.85),
    ("Max Pezzali", "Hanno ucciso l'Uomo Ragno", "fit", 0.85),
    ("Jovanotti", "Ragazzo fortunato", "fit", 0.85),
    ("Negramaro", "Estate", "weak_fit", 0.60),
    ("Måneskin", "ZITTO E BUONI", "weak_fit", 0.60),
    ("Rosa Chemical", "Made in Italy", "fit", 0.85),
    ("Ghali", "Cara Italia", "weak_fit", 0.60),
    ("Sfera Ebbasta", "Tran Tran", "weak_fit", 0.50),
    ("Lazza", "CENERE", "weak_fit", 0.50),
    ("Club Dogo", "P.V.P.", "weak_fit", 0.50),
    ("Fabio Rovazzi", "Andiamo a comandare", "fit", 0.90),
    ("Elettra Lamborghini", "Pem Pem", "fit", 0.90),
    ("Raffaella Carrà", "A far l'amore comincia tu", "fit", 0.95),
    ("Gabry Ponte", "Geordie", "fit", 0.90),
    ("Benny Benassi", "Satisfaction", "fit", 0.95),
    ("Gigi D'Agostino", "L'amour toujours", "fit", 0.95),
    ("Paola & Chiara", "Fino Alla Fine", "fit", 0.85),
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


def _artists(candidate) -> list[str]:
    values = candidate.get("artists", []) if isinstance(candidate, dict) else []
    if isinstance(values, dict):
        values = [values]
    return [str(item.get("name", "")) for item in values if isinstance(item, dict)]


def _title(candidate) -> str:
    if not isinstance(candidate, dict):
        return ""
    return str(candidate.get("trackTitle") or candidate.get("name") or candidate.get("title") or "")


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


def test_reccobeats_live_probe() -> None:
    results = []
    with httpx.Client(timeout=15.0, headers={"Accept": "application/json", "User-Agent": "PlaylistMuse-ReccoBeats-Probe/1.0"}) as client:
        for artist, title, verdict, confidence in TRACKS:
            row = {
                "artist": artist,
                "title": title,
                "creative_verdict": verdict,
                "creative_confidence": confidence,
            }
            search = _get(
                client,
                f"{BASE}/track/search",
                params={"searchText": title, "size": 20, "page": 0},
            )
            row["search_status"] = search.status_code
            try:
                candidates = _content(search.json()) if search.is_success else []
            except ValueError:
                candidates = []
            row["search_candidates"] = len(candidates)

            expected_title = _norm(title)
            expected_artist = _norm(artist)
            selected = None
            for candidate in candidates:
                candidate_title = _norm(_title(candidate))
                candidate_artists = {_norm(value) for value in _artists(candidate)}
                if candidate_title == expected_title and expected_artist in candidate_artists:
                    selected = candidate
                    break
            if selected is None:
                for candidate in candidates:
                    if _norm(_title(candidate)) == expected_title:
                        selected = candidate
                        row["title_only_match"] = True
                        break

            if not isinstance(selected, dict) or not selected.get("id"):
                row["matched"] = False
                results.append(row)
                time.sleep(0.15)
                continue

            row["matched"] = True
            row["matched_title"] = _title(selected)
            row["matched_artists"] = _artists(selected)
            row["reccobeats_id"] = selected.get("id")
            row["isrc"] = selected.get("isrc")

            features = _get(client, f"{BASE}/track/{selected['id']}/audio-features")
            row["features_status"] = features.status_code
            if features.is_success:
                try:
                    payload = features.json()
                except ValueError:
                    payload = {}
                if isinstance(payload, dict):
                    for key in (
                        "danceability",
                        "energy",
                        "valence",
                        "tempo",
                        "liveness",
                        "acousticness",
                        "instrumentalness",
                        "speechiness",
                        "loudness",
                    ):
                        if key in payload:
                            row[key] = payload[key]
            results.append(row)
            time.sleep(0.15)

    matched = [row for row in results if row.get("matched")]
    featured = [row for row in matched if row.get("features_status") == 200 and "energy" in row]
    summary = {
        "requested": len(results),
        "matched": len(matched),
        "features": len(featured),
        "match_rate": round(len(matched) / len(results), 3),
        "feature_rate": round(len(featured) / len(results), 3),
    }
    print("RECCOBEATS_PROBE=" + json.dumps({"summary": summary, "tracks": results}, ensure_ascii=False, sort_keys=True))
    assert False, "intentional live probe; inspect RECCOBEATS_PROBE in CI log"
