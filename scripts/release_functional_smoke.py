#!/usr/bin/env python3
"""Functional HTTP checks for a running PlaylistMuse container."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Response:
    status: int
    body: bytes
    content_type: str

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text())


class FunctionalCheckError(AssertionError):
    """Raised when a release functional check fails."""


def request(
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> Response:
    data = None
    headers = {"Accept": "application/json, text/html;q=0.9, */*;q=0.8"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return Response(
                status=response.status,
                body=response.read(),
                content_type=response.headers.get("Content-Type", ""),
            )
    except urllib.error.HTTPError as error:
        return Response(
            status=error.code,
            body=error.read(),
            content_type=error.headers.get("Content-Type", ""),
        )


def expect_status(response: Response, expected: int, label: str) -> None:
    if response.status != expected:
        raise FunctionalCheckError(
            f"{label}: expected HTTP {expected}, received {response.status}: "
            f"{response.text()[:500]}"
        )


def expect_json(response: Response, expected_status: int, label: str) -> Any:
    expect_status(response, expected_status, label)
    try:
        return response.json()
    except json.JSONDecodeError as error:
        raise FunctionalCheckError(
            f"{label}: response is not valid JSON: {response.text()[:500]}"
        ) from error


def check_public_pages(base_url: str) -> None:
    home = request(base_url, "GET", "/")
    expect_status(home, 200, "home page")
    if "PlaylistMuse" not in home.text() or "text/html" not in home.content_type:
        raise FunctionalCheckError("home page: expected PlaylistMuse HTML")

    playlist = request(base_url, "GET", "/static/playlist.html")
    expect_status(playlist, 200, "playlist page")
    if "Your playlist" not in playlist.text():
        raise FunctionalCheckError("playlist page: expected results UI")

    assets = (
        "/static/app.js",
        "/static/playlist.js",
        "/static/style.css",
        "/static/playlistmuse-favicon.svg",
    )
    for path in assets:
        asset = request(base_url, "GET", path)
        expect_status(asset, 200, f"static asset {path}")
        if not asset.body:
            raise FunctionalCheckError(f"static asset {path}: empty response")


def check_read_only_api(base_url: str) -> None:
    health = expect_json(request(base_url, "GET", "/api/health"), 200, "health")
    if health != {"status": "healthy", "application": "PlaylistMuse"}:
        raise FunctionalCheckError(f"health: unexpected payload {health!r}")

    openapi = expect_json(request(base_url, "GET", "/openapi.json"), 200, "OpenAPI")
    if openapi.get("info", {}).get("title") != "PlaylistMuse":
        raise FunctionalCheckError("OpenAPI: incorrect application title")
    print(f"OpenAPI application version: {openapi.get('info', {}).get('version', '')}")

    expect_json(request(base_url, "GET", "/api/ai/profiles"), 200, "AI profiles")
    expect_json(request(base_url, "GET", "/api/lastfm/status"), 200, "Last.fm status")
    expect_json(request(base_url, "GET", "/api/youtube/settings"), 200, "YouTube settings")
    expect_json(request(base_url, "GET", "/api/youtube/status"), 200, "YouTube status")


def check_validation_boundaries(base_url: str) -> None:
    cases = (
        (
            "POST",
            "/api/playlists/generate",
            {"prompt": "x", "track_count": 5},
            422,
            "short generation prompt",
        ),
        (
            "POST",
            "/api/playlists/generate-from-seed",
            {},
            422,
            "missing seed request",
        ),
        (
            "POST",
            "/api/playlists/replace-track",
            {},
            422,
            "missing replacement request",
        ),
        (
            "POST",
            "/api/youtube/playlists",
            {
                "title": "Invalid empty playlist",
                "description": "",
                "privacy_status": "PRIVATE",
                "video_ids": [],
            },
            422,
            "empty YouTube playlist",
        ),
        (
            "PUT",
            "/api/lastfm/settings",
            {"api_key": ""},
            422,
            "empty Last.fm key",
        ),
        (
            "PUT",
            "/api/youtube/settings",
            {"client_id": "", "client_secret": ""},
            422,
            "empty YouTube credentials",
        ),
    )
    for method, path, payload, status, label in cases:
        expect_status(request(base_url, method, path, payload), status, label)

    mismatch = request(
        base_url,
        "PUT",
        "/api/settings",
        {
            "provider": "gemini",
            "api_key": "sk-or-intentionally-wrong-provider",
            "model": "gemini-test",
            "fallback_1": "",
            "fallback_2": "",
            "base_url": "",
        },
    )
    expect_status(mismatch, 400, "cross-provider API key rejection")

    expect_status(
        request(base_url, "DELETE", "/api/ai/providers/not-a-provider"),
        404,
        "unknown AI provider",
    )
    expect_status(request(base_url, "GET", "/api/not-a-real-route"), 404, "unknown route")


def configure_persistent_state(base_url: str) -> None:
    onboarding = expect_json(
        request(base_url, "GET", "/api/onboarding"),
        200,
        "fresh onboarding state",
    )
    if onboarding.get("required") is not True:
        raise FunctionalCheckError(f"fresh onboarding state: unexpected {onboarding!r}")

    initial_settings = expect_json(
        request(base_url, "GET", "/api/settings"),
        200,
        "fresh AI settings",
    )
    if initial_settings.get("configured") is not False:
        raise FunctionalCheckError(
            f"fresh AI settings should be unconfigured: {initial_settings!r}"
        )

    configured = expect_json(
        request(
            base_url,
            "PUT",
            "/api/settings",
            {
                "provider": "ollama",
                "api_key": "",
                "model": "release-smoke-model",
                "fallback_1": "",
                "fallback_2": "",
                "base_url": "http://127.0.0.1:11434",
            },
        ),
        200,
        "save Ollama settings",
    )
    if not configured.get("configured") or configured.get("provider") != "ollama":
        raise FunctionalCheckError(f"save Ollama settings: unexpected {configured!r}")

    acknowledged = expect_json(
        request(base_url, "POST", "/api/onboarding/acknowledge"),
        200,
        "acknowledge onboarding",
    )
    if acknowledged != {"required": False}:
        raise FunctionalCheckError(f"acknowledge onboarding: unexpected {acknowledged!r}")


def check_persisted_state(base_url: str) -> None:
    onboarding = expect_json(
        request(base_url, "GET", "/api/onboarding"),
        200,
        "persisted onboarding state",
    )
    if onboarding != {"required": False}:
        raise FunctionalCheckError(f"persisted onboarding state: unexpected {onboarding!r}")

    settings = expect_json(
        request(base_url, "GET", "/api/settings"),
        200,
        "persisted AI settings",
    )
    expected = {
        "provider": "ollama",
        "model": "release-smoke-model",
        "base_url": "http://127.0.0.1:11434",
        "configured": True,
    }
    mismatches = {
        key: (settings.get(key), value)
        for key, value in expected.items()
        if settings.get(key) != value
    }
    if mismatches:
        raise FunctionalCheckError(f"persisted AI settings mismatch: {mismatches!r}")

    profiles = expect_json(
        request(base_url, "GET", "/api/ai/profiles"),
        200,
        "persisted AI profiles",
    )
    if profiles.get("active_provider") != "ollama" or not profiles.get("configured"):
        raise FunctionalCheckError(f"persisted AI profiles: unexpected {profiles!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5780")
    parser.add_argument("--phase", choices=("initial", "persisted"), required=True)
    args = parser.parse_args()

    check_public_pages(args.base_url)
    check_read_only_api(args.base_url)
    check_validation_boundaries(args.base_url)
    if args.phase == "initial":
        configure_persistent_state(args.base_url)
    else:
        check_persisted_state(args.base_url)

    print(f"PlaylistMuse functional smoke phase '{args.phase}' passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FunctionalCheckError, urllib.error.URLError, TimeoutError) as error:
        print(f"Functional smoke failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
