#!/usr/bin/env python3
"""Cold-vs-warm cache benchmark for one generation request.

Drives a running PlaylistMuse instance over HTTP (same convention as
scripts/vps-smoke-test.sh), instead of invoking the async generation pipeline
standalone -- this reuses the target instance's real configured AI provider and
avoids re-implementing app setup outside the app itself.

Requires the target instance to already have a working AI provider configured
(this script does not configure one). Clears the on-disk lookup caches before
the "cold" run via the same endpoint the Storage page's "Clear cache" button
uses, then repeats the identical prompt for the "warm" run.

Usage:
    python scripts/benchmark_generation_cache.py [--url http://127.0.0.1:5780] [--prompt "..."]
"""

from __future__ import annotations

import argparse
import sys

import httpx

DEFAULT_PROMPT = "Upbeat 2010s indie pop for a road trip, 15 tracks."


def _run_generation(client: httpx.Client, prompt: str, track_count: int) -> dict:
    response = client.post(
        "/api/playlists/generate",
        json={"prompt": prompt, "track_count": track_count},
        timeout=180.0,
    )
    response.raise_for_status()
    return response.json()


def _storage_snapshot(client: httpx.Client) -> dict:
    response = client.get("/api/diagnostics/storage", timeout=30.0)
    response.raise_for_status()
    return response.json()


def _cache_hits_misses(storage: dict) -> dict[str, tuple[int, int]]:
    return {
        cache["name"]: (cache["hits"], cache["misses"])
        for cache in storage.get("caches", [])
    }


def _print_run(label: str, meta: dict) -> None:
    print(f"\n{label}")
    print(f"  total duration: {meta.get('duration_ms')} ms")
    stages = meta.get("stage_timings_ms") or {}
    for stage, elapsed_ms in sorted(stages.items()):
        print(f"    {stage}: {elapsed_ms} ms")


def _print_cache_delta(label: str, before: dict, after: dict) -> None:
    print(f"\n{label} -- cache activity during this run")
    for name in sorted(set(before) | set(after)):
        before_hits, before_misses = before.get(name, (0, 0))
        after_hits, after_misses = after.get(name, (0, 0))
        hits = after_hits - before_hits
        misses = after_misses - before_misses
        if hits or misses:
            print(f"  {name}: +{hits} hits, +{misses} misses")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:5780", help="Base URL of a running instance")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Prompt to generate, run twice")
    parser.add_argument("--track-count", type=int, default=15)
    args = parser.parse_args()

    with httpx.Client(base_url=args.url) as client:
        health = client.get("/api/health", timeout=10.0)
        health.raise_for_status()

        print("Clearing caches for the cold run...")
        client.post("/api/diagnostics/storage/clear-cache", timeout=30.0).raise_for_status()

        before_cold = _cache_hits_misses(_storage_snapshot(client))
        cold_result = _run_generation(client, args.prompt, args.track_count)
        after_cold = _cache_hits_misses(_storage_snapshot(client))
        cold_meta = cold_result.get("generation_meta", {})
        _print_run("Cold run (empty caches)", cold_meta)
        _print_cache_delta("Cold run", before_cold, after_cold)

        before_warm = after_cold
        warm_result = _run_generation(client, args.prompt, args.track_count)
        after_warm = _cache_hits_misses(_storage_snapshot(client))
        warm_meta = warm_result.get("generation_meta", {})
        _print_run("Warm run (same prompt, caches populated)", warm_meta)
        _print_cache_delta("Warm run", before_warm, after_warm)

        cold_ms = cold_meta.get("duration_ms")
        warm_ms = warm_meta.get("duration_ms")
        if isinstance(cold_ms, int | float) and isinstance(warm_ms, int | float):
            delta = int(cold_ms - warm_ms)
            print(f"\nTotal duration: cold {cold_ms} ms -> warm {warm_ms} ms ({delta:+d} ms)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
