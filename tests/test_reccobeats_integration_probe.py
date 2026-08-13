from __future__ import annotations

import asyncio
import json
import time

from backend.reccobeats_features import audio_evidence_for_tracks


TRACKS = [
    {"artist": "Boomdabash", "title": "Karaoke"},
    {"artist": "Negramaro", "title": "Estate"},
    {"artist": "Ghali", "title": "Cara Italia"},
    {"artist": "Sfera Ebbasta", "title": "Tran Tran"},
    {"artist": "Lazza", "title": "CENERE"},
    {"artist": "Elettra Lamborghini", "title": "Pem Pem"},
]


def test_reccobeats_integrated_live_probe() -> None:
    started = time.perf_counter()
    evidence = asyncio.run(audio_evidence_for_tracks(TRACKS))
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
    print("RECCOBEATS_BOUNDED_PROBE=" + json.dumps({"summary": summary, "tracks": rows}, ensure_ascii=False, sort_keys=True))
    assert False, "intentional live probe; inspect RECCOBEATS_BOUNDED_PROBE"
