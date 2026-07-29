"""Run a small real-data MusicBrainz smoke test and write a JSON report."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from backend.metadata.musicbrainz import MusicBrainzClient

SAMPLE_TRACKS: tuple[tuple[str, str], ...] = (
    ("Back in Black", "AC/DC"),
    ("Gimme Shelter", "The Rolling Stones"),
    ("Time", "Pink Floyd"),
    ("Smells Like Teen Spirit", "Nirvana"),
    ("Billie Jean", "Michael Jackson"),
)


async def run_smoke_test() -> dict[str, Any]:
    results: list[dict[str, Any]] = []

    async with MusicBrainzClient(timeout_seconds=15.0) as client:
        for title, artists in SAMPLE_TRACKS:
            try:
                match = await client.search_track(title, artists)
                results.append(
                    {
                        "input": {"title": title, "artists": artists},
                        "musicbrainz": match,
                        "error": None,
                    }
                )
            except Exception as error:  # Real-service diagnostics belong in the report.
                results.append(
                    {
                        "input": {"title": title, "artists": artists},
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
    error_count = sum(1 for result in results if result.get("error"))

    return {
        "schema_version": 1,
        "sample_count": len(SAMPLE_TRACKS),
        "matched_count": matched_count,
        "error_count": error_count,
        "success": matched_count >= 4 and error_count <= 1,
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
