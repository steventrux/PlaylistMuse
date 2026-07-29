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

from backend.metadata.musicbrainz_decision import with_musicbrainz_decision
from backend.metadata.musicbrainz_policy import PolicyAwareMusicBrainzClient

SAMPLE_TRACKS: tuple[dict[str, Any], ...] = (
    {"title": "Back in Black", "artists": "AC/DC", "duration_ms": 255000},
    {"title": "Gimme Shelter", "artists": "The Rolling Stones", "duration_ms": 271000},
    {"title": "Time", "artists": "Pink Floyd", "duration_ms": 413000},
    {"title": "Smells Like Teen Spirit", "artists": "Nirvana", "duration_ms": 301000},
    {"title": "Billie Jean", "artists": "Michael Jackson", "duration_ms": 294000},
)

DEFAULT_EXCLUSIONS = {
    "exclude_live": True,
    "exclude_covers": True,
    "exclude_remixes": True,
}


async def run_smoke_test() -> dict[str, Any]:
    results: list[dict[str, Any]] = []

    async with PolicyAwareMusicBrainzClient(timeout_seconds=15.0) as client:
        for sample in SAMPLE_TRACKS:
            try:
                raw_match = await client.search_track(
                    sample["title"],
                    sample["artists"],
                    duration_ms=sample["duration_ms"],
                    exclusions=DEFAULT_EXCLUSIONS,
                )
                match = with_musicbrainz_decision(raw_match, DEFAULT_EXCLUSIONS)
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

    decisions = [
        result["musicbrainz"].get("decision")
        for result in results
        if isinstance(result.get("musicbrainz"), dict)
    ]
    matched_count = decisions.count("matched")
    ambiguous_count = decisions.count("ambiguous")
    rejected_count = decisions.count("rejected")
    error_count = sum(1 for result in results if result.get("error"))
    false_positive_count = sum(
        1
        for result in results
        if isinstance(result.get("musicbrainz"), dict)
        and result["musicbrainz"].get("decision") == "matched"
        and (
            result["musicbrainz"].get("policy_excluded_categories")
            or (
                result["musicbrainz"].get("duration_delta_ms") is not None
                and int(result["musicbrainz"]["duration_delta_ms"]) > 15000
            )
        )
    )

    classified_count = matched_count + ambiguous_count + rejected_count
    return {
        "schema_version": 4,
        "sample_count": len(SAMPLE_TRACKS),
        "exclusions": DEFAULT_EXCLUSIONS,
        "matched_count": matched_count,
        "ambiguous_count": ambiguous_count,
        "rejected_count": rejected_count,
        "error_count": error_count,
        "false_positive_count": false_positive_count,
        "success": (
            matched_count >= 3
            and classified_count + error_count == len(SAMPLE_TRACKS)
            and ambiguous_count >= 1
            and false_positive_count == 0
            and error_count <= 1
        ),
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
