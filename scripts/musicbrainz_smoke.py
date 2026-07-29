"""Run a small real-data MusicBrainz smoke test and write a JSON report."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.metadata.musicbrainz import MusicBrainzClient

SAMPLE_TRACKS: tuple[dict[str, Any], ...] = (
    {"title": "Back in Black", "artists": "AC/DC", "duration_ms": 255000},
    {"title": "Gimme Shelter", "artists": "The Rolling Stones", "duration_ms": 271000},
    {"title": "Time", "artists": "Pink Floyd", "duration_ms": 413000},
    {"title": "Smells Like Teen Spirit", "artists": "Nirvana", "duration_ms": 301000},
    {"title": "Billie Jean", "artists": "Michael Jackson", "duration_ms": 294000},
)


async def run_smoke_test() -> dict[str, Any]:
    results: list[dict[str, Any]] = []

    async with MusicBrainzClient(timeout_seconds=15.0) as client:
        for sample in SAMPLE_TRACKS:
            try:
                match = await client.search_track(
                    sample["title"],
                    sample["artists"],
                    duration_ms=sample["duration_ms"],
                )
                results.append(
                    {
                        "input": sample,
                        "musicbrainz": match,
                        "error": None,
                    }
                )
            except Exception as error:  # Real-service diagnostics belong in the report.
                results.append(
                    {
                        "input": sample,
                        "musicbrainz": None,
                        "error": f"{type(error).__name__}: {error}",
                    }
                )

    matched_count = sum(
        1
        for result in results
        if isinstance(result.get("musicbrainz"), dict)
        and result["musicbrainz"].get("matched") is True
    )
    canonical_count = sum(
        1
        for result in results
        if isinstance(result.get("musicbrainz"), dict)
        and result["musicbrainz"].get("matched") is True
        and (result["musicbrainz"].get("duration_delta_ms") or 0) <= 15000
        and (result["musicbrainz"].get("version_penalty") or 0) <= 10
    )
    error_count = sum(1 for result in results if result.get("error"))

    return {
        "schema_version": 2,
        "sample_count": len(SAMPLE_TRACKS),
        "matched_count": matched_count,
        "canonical_count": canonical_count,
        "error_count": error_count,
        "success": matched_count >= 4 and canonical_count >= 4 and error_count <= 1,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/musicbrainz-smoke-report.json"),
    )
    args = parser.parse_args()

    report = asyncio.run(run_smoke_test())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
