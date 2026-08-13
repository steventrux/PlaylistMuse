from __future__ import annotations

import asyncio
import json
import time

from backend import reccobeats_features


TRACKS = [
    {"artist": "Paola & Chiara", "title": "Vamos a bailar (Esta vida nueva)"},
    {"artist": "Takagi & Ketra", "title": "Roma-Bangkok"},
    {"artist": "Baby K", "title": "Da zero a cento"},
    {"artist": "The Kolors", "title": "Italodisco"},
    {"artist": "Annalisa", "title": "Mon Amour"},
    {"artist": "Rocco Hunt", "title": "A Un Passo Dalla Luna"},
    {"artist": "Boomdabash", "title": "Karaoke"},
    {"artist": "Fred De Palma", "title": "Una volta ancora"},
    {"artist": "J-Ax", "title": "Ostia Lido"},
    {"artist": "Max Pezzali", "title": "Hanno ucciso l'Uomo Ragno"},
    {"artist": "Jovanotti", "title": "Ragazzo fortunato"},
    {"artist": "Negramaro", "title": "Estate"},
    {"artist": "Måneskin", "title": "ZITTO E BUONI"},
    {"artist": "Rosa Chemical", "title": "Made in Italy"},
    {"artist": "Ghali", "title": "Cara Italia"},
    {"artist": "Sfera Ebbasta", "title": "Tran Tran"},
    {"artist": "Lazza", "title": "CENERE"},
    {"artist": "Club Dogo", "title": "P.V.P."},
    {"artist": "Fabio Rovazzi", "title": "Andiamo a comandare"},
    {"artist": "Elettra Lamborghini", "title": "Pem Pem"},
    {"artist": "Raffaella Carrà", "title": "A far l'amore comincia tu"},
    {"artist": "Gabry Ponte", "title": "Geordie"},
    {"artist": "Benny Benassi", "title": "Satisfaction"},
    {"artist": "Gigi D'Agostino", "title": "L'amour toujours"},
    {"artist": "Paola & Chiara", "title": "Fino Alla Fine"},
]


def test_reccobeats_integrated_live_probe() -> None:
    reccobeats_features.MAX_CONCURRENT_REQUESTS = 1
    started = time.perf_counter()
    evidence = asyncio.run(reccobeats_features.audio_evidence_for_tracks(TRACKS))
    elapsed = round(time.perf_counter() - started, 3)
    rows = []
    for track, item in zip(TRACKS, evidence, strict=True):
        rows.append(
            {
                **track,
                "available": item.available,
                "match_source": item.match_source,
                "features": item.features,
            }
        )
    summary = {
        "requested": len(rows),
        "available": sum(1 for row in rows if row["available"]),
        "track_search": sum(1 for row in rows if row["match_source"] == "track_search"),
        "artist_catalog": sum(1 for row in rows if row["match_source"] == "artist_catalog"),
        "elapsed_seconds": elapsed,
    }
    print("RECCOBEATS_INTEGRATED_PROBE=" + json.dumps({"summary": summary, "tracks": rows}, ensure_ascii=False, sort_keys=True))
    assert False, "intentional live probe; inspect RECCOBEATS_INTEGRATED_PROBE"
