"""Summarize PlaylistMuse MusicBrainz shadow NDJSON without network access."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

DEFAULT_INPUT = Path("data/musicbrainz-shadow.ndjson")


def _identity(item: dict[str, Any]) -> str:
    source = item.get("input") or {}
    artists = " ".join(str(source.get("artists", "")).casefold().split())
    title = " ".join(str(source.get("title", "")).casefold().split())
    return f"{artists}::{title}" if artists and title else ""


def _exclusion_key(value: Any) -> str:
    exclusions = value if isinstance(value, dict) else {}
    return ",".join(
        (
            f"live={int(bool(exclusions.get('exclude_live', True)))}",
            f"covers={int(bool(exclusions.get('exclude_covers', True)))}",
            f"remixes={int(bool(exclusions.get('exclude_remixes', True)))}",
        )
    )


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_records(path: Path) -> tuple[list[dict[str, Any]], list[int]]:
    """Load valid object records and return malformed 1-based line numbers."""
    records: list[dict[str, Any]] = []
    malformed_lines: list[int] = []
    if not path.exists():
        return records, malformed_lines

    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            malformed_lines.append(line_number)
            continue
        if not isinstance(value, dict):
            malformed_lines.append(line_number)
            continue
        records.append(value)
    return records, malformed_lines


def _distribution(values: Iterable[float]) -> dict[str, float | int | None]:
    collected = list(values)
    if not collected:
        return {"count": 0, "min": None, "mean": None, "max": None}
    return {
        "count": len(collected),
        "min": round(min(collected), 2),
        "mean": round(statistics.fmean(collected), 2),
        "max": round(max(collected), 2),
    }


def analyze_records(
    records: list[dict[str, Any]],
    *,
    malformed_lines: list[int] | None = None,
) -> dict[str, Any]:
    decisions: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    exclusion_combinations: Counter[str] = Counter()
    attempts: Counter[int] = Counter()
    identities: Counter[str] = Counter()
    identity_mbids: defaultdict[str, set[str]] = defaultdict(set)
    confidences: list[float] = []
    duration_deltas: list[float] = []
    candidate_count = 0
    relationship_complete = 0
    relationship_evidence = 0
    retry_recovered = 0
    sampled_results = 0

    for record in records:
        exclusion_combinations[_exclusion_key(record.get("exclusions"))] += 1
        for item in record.get("results") or []:
            if not isinstance(item, dict):
                continue
            sampled_results += 1
            identity = _identity(item)
            if identity:
                identities[identity] += 1

            raw_attempts = item.get("attempts", 1)
            try:
                attempt_count = max(1, int(raw_attempts))
            except (TypeError, ValueError):
                attempt_count = 1
            attempts[attempt_count] += 1

            error = item.get("error")
            if error:
                errors[str(error)] += 1
                continue

            match = item.get("musicbrainz")
            if not isinstance(match, dict):
                decisions["missing"] += 1
                continue

            candidate_count += 1
            decision = str(match.get("decision") or "missing")
            decisions[decision] += 1
            if attempt_count > 1:
                retry_recovered += 1

            mbid = str(match.get("recording_mbid") or "").strip()
            if identity and mbid:
                identity_mbids[identity].add(mbid)

            for reason in match.get("decision_reasons") or []:
                reasons[str(reason)] += 1
            for category in match.get("version_categories") or []:
                categories[str(category)] += 1

            confidence = _number(match.get("confidence"))
            if confidence is not None:
                confidences.append(confidence)
            duration_delta = _number(match.get("duration_delta_ms"))
            if duration_delta is not None:
                duration_deltas.append(duration_delta)

            if match.get("relationship_lookup_complete") is True:
                relationship_complete += 1
            if (
                match.get("relationship_version_categories")
                or match.get("relationship_evidence_recording_mbids")
            ):
                relationship_evidence += 1

    unstable = {
        identity: sorted(mbids)
        for identity, mbids in sorted(identity_mbids.items())
        if len(mbids) > 1
    }
    repeated = {
        identity: count
        for identity, count in sorted(identities.items())
        if count > 1
    }
    total_outcomes = sum(decisions.values()) + sum(errors.values())

    return {
        "schema_version": 1,
        "record_count": len(records),
        "malformed_line_count": len(malformed_lines or []),
        "malformed_lines": list(malformed_lines or []),
        "sampled_result_count": sampled_results,
        "outcome_count": total_outcomes,
        "decisions": dict(sorted(decisions.items())),
        "errors": dict(sorted(errors.items())),
        "decision_reasons": dict(sorted(reasons.items())),
        "version_categories": dict(sorted(categories.items())),
        "exclusion_combinations": dict(sorted(exclusion_combinations.items())),
        "attempts": {str(key): value for key, value in sorted(attempts.items())},
        "retry_recovered_count": retry_recovered,
        "candidate_count": candidate_count,
        "relationship_lookup_complete_count": relationship_complete,
        "relationship_evidence_count": relationship_evidence,
        "relationship_lookup_complete_rate": round(
            relationship_complete / candidate_count,
            4,
        )
        if candidate_count
        else None,
        "confidence": _distribution(confidences),
        "duration_delta_ms": _distribution(duration_deltas),
        "repeated_identities": repeated,
        "unstable_recording_mbids": unstable,
    }


def _format_mapping(mapping: dict[str, Any]) -> str:
    if not mapping:
        return "nessuno"
    return ", ".join(f"{key}: {value}" for key, value in mapping.items())


def render_text(report: dict[str, Any]) -> str:
    lines = [
        "=== MUSICBRAINZ SHADOW REPORT ===",
        f"Record: {report['record_count']}",
        f"Righe malformate: {report['malformed_line_count']}",
        f"Risultati campionati: {report['sampled_result_count']}",
        f"Decisioni: {_format_mapping(report['decisions'])}",
        f"Errori: {_format_mapping(report['errors'])}",
        f"Tentativi: {_format_mapping(report['attempts'])}",
        f"Retry recuperati: {report['retry_recovered_count']}",
        f"Motivi: {_format_mapping(report['decision_reasons'])}",
        f"Categorie: {_format_mapping(report['version_categories'])}",
        f"Combinazioni selettori: {_format_mapping(report['exclusion_combinations'])}",
        (
            "Relazioni complete: "
            f"{report['relationship_lookup_complete_count']}/{report['candidate_count']}"
        ),
        f"Identità ripetute: {len(report['repeated_identities'])}",
        f"Identità con MBID instabile: {len(report['unstable_recording_mbids'])}",
    ]
    if report["malformed_lines"]:
        lines.append(
            "Linee malformate: "
            + ", ".join(str(value) for value in report["malformed_lines"])
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()

    if not args.input.exists():
        print(f"File shadow non trovato: {args.input}")
        return 2

    records, malformed_lines = load_records(args.input)
    report = analyze_records(records, malformed_lines=malformed_lines)
    print(render_text(report))

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
