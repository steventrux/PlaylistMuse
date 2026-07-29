"""Validate MusicBrainz live, remix and cover policies against real data."""

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

ALL_ALLOWED = {
    "exclude_live": False,
    "exclude_covers": False,
    "exclude_remixes": False,
}
ALL_EXCLUDED = {
    "exclude_live": True,
    "exclude_covers": True,
    "exclude_remixes": True,
}

SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "id": "cover",
        "title": "Hurt",
        "artists": "Johnny Cash",
        "duration_ms": 217_000,
        "category": "cover",
        "option": "exclude_covers",
        "reason": "excluded_cover",
    },
    {
        "id": "live",
        "title": "Thunderstruck",
        "artists": "AC/DC",
        "duration_ms": 394_000,
        "category": "live",
        "option": "exclude_live",
        "reason": "excluded_live",
    },
    {
        "id": "remix",
        "title": "Blue Monday 1988 (12'' mix)",
        "artists": "New Order",
        "duration_ms": 430_000,
        "category": "remix",
        "option": "exclude_remixes",
        "reason": "excluded_remix",
    },
)

BASELINE = {
    "id": "studio-control",
    "title": "Back in Black",
    "artists": "AC/DC",
    "duration_ms": 255_000,
}


def _compact(match: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(match, dict):
        return None
    return {
        "recording_mbid": match.get("recording_mbid"),
        "recording_title": match.get("recording_title"),
        "recording_disambiguation": match.get("recording_disambiguation"),
        "release_title": match.get("release_title"),
        "duration_delta_ms": match.get("duration_delta_ms"),
        "confidence": match.get("confidence"),
        "decision": match.get("decision"),
        "decision_reasons": match.get("decision_reasons"),
        "version_categories": match.get("version_categories"),
        "relationship_version_categories": match.get(
            "relationship_version_categories"
        ),
        "relationship_evidence_recording_mbids": match.get(
            "relationship_evidence_recording_mbids"
        ),
        "policy_excluded_categories": match.get("policy_excluded_categories"),
        "relationship_lookup_complete": match.get("relationship_lookup_complete"),
        "relationship_lookup_error": match.get("relationship_lookup_error"),
        "work_relationships": match.get("work_relationships"),
        "recording_relationships": match.get("recording_relationships"),
    }


async def _lookup(
    client: PolicyAwareMusicBrainzClient,
    sample: dict[str, Any],
    exclusions: dict[str, bool],
) -> dict[str, Any]:
    try:
        raw = await client.search_track(
            sample["title"],
            sample["artists"],
            duration_ms=sample.get("duration_ms"),
            exclusions=exclusions,
        )
        decided = with_musicbrainz_decision(raw, exclusions)
        return {"match": _compact(decided), "error": None}
    except Exception as error:  # Real-service diagnostics belong in the report.
        return {
            "match": None,
            "error": f"{type(error).__name__}: {error}",
        }


async def run_option_matrix() -> dict[str, Any]:
    results: list[dict[str, Any]] = []

    async with PolicyAwareMusicBrainzClient(timeout_seconds=20.0) as client:
        for scenario in SCENARIOS:
            allowed_policy = dict(ALL_ALLOWED)
            excluded_policy = dict(ALL_ALLOWED)
            excluded_policy[scenario["option"]] = True

            allowed = await _lookup(client, scenario, allowed_policy)
            excluded = await _lookup(client, scenario, excluded_policy)

            allowed_match = allowed.get("match") or {}
            excluded_match = excluded.get("match") or {}
            allowed_categories = set(allowed_match.get("version_categories") or [])
            excluded_categories = set(excluded_match.get("version_categories") or [])
            excluded_reasons = set(excluded_match.get("decision_reasons") or [])

            checks = {
                "allowed_category_detected": scenario["category"] in allowed_categories,
                "allowed_is_match": allowed_match.get("decision") == "matched",
                "excluded_category_detected": scenario["category"] in excluded_categories,
                "excluded_is_not_match": excluded_match.get("decision") != "matched",
                "excluded_reason_present": scenario["reason"] in excluded_reasons,
                "no_errors": not allowed.get("error") and not excluded.get("error"),
            }
            results.append(
                {
                    "scenario": scenario,
                    "allowed_policy": allowed_policy,
                    "excluded_policy": excluded_policy,
                    "allowed": allowed,
                    "excluded": excluded,
                    "checks": checks,
                    "success": all(checks.values()),
                }
            )

        baseline = await _lookup(client, BASELINE, ALL_EXCLUDED)

    baseline_match = baseline.get("match") or {}
    baseline_checks = {
        "matched_with_all_exclusions": baseline_match.get("decision") == "matched",
        "no_excluded_categories": not baseline_match.get("policy_excluded_categories"),
        "no_error": not baseline.get("error"),
    }
    baseline_result = {
        "scenario": BASELINE,
        "policy": ALL_EXCLUDED,
        "result": baseline,
        "checks": baseline_checks,
        "success": all(baseline_checks.values()),
    }

    failed_scenarios = [item["scenario"]["id"] for item in results if not item["success"]]
    success = not failed_scenarios and baseline_result["success"]
    return {
        "schema_version": 2,
        "scenario_count": len(results),
        "successful_scenarios": sum(1 for item in results if item["success"]),
        "failed_scenarios": failed_scenarios,
        "baseline_success": baseline_result["success"],
        "success": success,
        "results": results,
        "baseline": baseline_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/musicbrainz-options-smoke-report.json"),
    )
    args = parser.parse_args()

    report = asyncio.run(run_option_matrix())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
