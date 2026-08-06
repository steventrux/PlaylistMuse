#!/usr/bin/env python3
"""Chromium end-to-end checks for the PlaylistMuse release candidate."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from playwright.sync_api import Page, Route, expect, sync_playwright


class BrowserCheckError(AssertionError):
    """Raised when the browser flow does not behave as expected."""


def mock_prompt_analysis(route: Route) -> None:
    request_payload = json.loads(route.request.post_data or "{}")
    good_clarity = int(request_payload.get("track_count", 25)) == 26
    payload: dict[str, Any] = {
        "score": 27,
        "level": "Detailed",
        "clarity": 80 if good_clarity else 100,
        "clarity_level": "Good" if good_clarity else "Excellent",
        "dimensions": 2,
        "hard_constraints": 1,
        "soft_constraints": 0,
        "structures": 0,
        "relations": 0,
        "issues": ["This diagnostic must stay hidden for Good and Excellent clarity."],
    }
    route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(payload),
    )


def assert_no_horizontal_overflow(page: Page, label: str) -> None:
    dimensions = page.evaluate(
        """() => ({
            viewport: document.documentElement.clientWidth,
            content: document.documentElement.scrollWidth,
        })"""
    )
    if dimensions["content"] > dimensions["viewport"] + 1:
        raise BrowserCheckError(f"{label}: horizontal overflow {dimensions!r}")


def test_home(page: Page, base_url: str) -> None:
    page.route("**/api/prompts/analyze", mock_prompt_analysis)
    page.goto(base_url, wait_until="networkidle")

    expect(page).to_have_title("PlaylistMuse")
    expect(page.locator("h1")).to_have_text("PlaylistMuse")
    expect(page.locator("#setup-dialog")).not_to_be_visible()
    expect(page.locator("#prompt-panel")).to_be_visible()
    expect(page.locator("#seed-panel")).to_be_hidden()

    page.locator("#prompt").fill("A focused rock playlist for a night drive")
    expect(page.locator("#generation-controls")).to_be_visible()
    expect(page.locator("#generate")).to_be_enabled(timeout=10_000)

    expect(page.locator("#prompt-complexity")).to_be_visible(timeout=3_000)
    page.locator("#prompt-complexity-trigger").click()
    expect(page.locator("#prompt-complexity-score")).to_have_text("Simple · 27/100")
    expect(page.locator("#prompt-clarity")).to_have_text("Clarity: Excellent")

    page.locator("#track-count").fill("26")
    page.locator("#track-count").dispatch_event("change")
    expect(page.locator("#prompt-clarity")).to_have_text("Clarity: Good", timeout=3_000)

    page.get_by_role("button", name="From Seed").click()
    expect(page.locator("#prompt-panel")).to_be_hidden()
    expect(page.locator("#seed-panel")).to_be_visible()
    page.locator("#seed-query").fill("A")
    expect(page.locator("#seed-search")).to_be_disabled()
    page.locator("#seed-query").fill("AC")
    expect(page.locator("#seed-search")).to_be_enabled()

    page.get_by_role("button", name="From Prompt").click()
    expect(page.locator("#prompt-panel")).to_be_visible()
    assert_no_horizontal_overflow(page, "desktop home")


def store_playlist_fixture(page: Page) -> None:
    playlist = {
        "name": "Release smoke playlist",
        "description": "A browser-rendered release validation playlist.",
        "prompt": "A focused rock playlist for a night drive",
        "requested_count": 3,
        "resolved_count": 3,
        "tracks": [
            {
                "video_id": "video-1",
                "title": "Track One",
                "artists": "Artist One",
                "album": "Album One",
                "duration": "3:30",
                "thumbnail_url": "",
                "url": "https://music.youtube.com/watch?v=video-1",
                "description": "Description one.",
                "reason": "Reason one.",
            },
            {
                "video_id": "video-2",
                "title": "Track Two",
                "artists": "Artist Two",
                "album": "Album Two",
                "duration": "4:10",
                "thumbnail_url": "",
                "url": "https://music.youtube.com/watch?v=video-2",
                "description": "Description two.",
                "reason": "Reason two.",
            },
            {
                "video_id": "video-3",
                "title": "Track Three",
                "artists": "Artist Three",
                "album": "Album Three",
                "duration": "2:20",
                "thumbnail_url": "",
                "url": "https://music.youtube.com/watch?v=video-3",
                "description": "Description three.",
                "reason": "Reason three.",
            },
        ],
    }
    generation_request = {
        "mode": "prompt",
        "prompt": playlist["prompt"],
        "track_count": 3,
        "options": {
            "exclude_live": True,
            "exclude_covers": True,
            "exclude_remixes": True,
        },
    }
    page.evaluate(
        """([playlist, request]) => {
            sessionStorage.setItem('playlistmuse-generated-playlist', JSON.stringify(playlist));
            sessionStorage.setItem('playlistmuse-generation-request', JSON.stringify(request));
        }""",
        [playlist, generation_request],
    )


def test_playlist_page(page: Page, base_url: str) -> None:
    store_playlist_fixture(page)
    page.goto(f"{base_url.rstrip('/')}/static/playlist.html", wait_until="networkidle")

    expect(page).to_have_title("Playlist · PlaylistMuse")
    expect(page.locator("#playlist-name")).to_have_value("Release smoke playlist")
    expect(page.locator("#playlist-summary")).to_have_text("3 tracks · 10 min")
    expect(page.locator("#track-list .track")).to_have_count(3)
    expect(page.locator("#playlist-cover-grid > *")).to_have_count(4)

    first_track = page.locator("#track-list .track").first
    first_track.click()
    expect(first_track).to_have_attribute("aria-expanded", "true")
    expect(first_track.get_by_text("Description one.")).to_be_visible()
    expect(first_track.get_by_role("button", name="Replace track")).to_be_visible()

    page.locator("#playlist-name").fill("Edited release smoke playlist")
    stored_name = page.evaluate(
        "JSON.parse(sessionStorage.getItem('playlistmuse-generated-playlist')).name"
    )
    if stored_name != "Edited release smoke playlist":
        raise BrowserCheckError(f"playlist title was not persisted in-session: {stored_name!r}")

    assert_no_horizontal_overflow(page, "desktop playlist")


def test_mobile_layout(browser, base_url: str) -> None:
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    page.route("**/api/prompts/analyze", mock_prompt_analysis)
    page.goto(base_url, wait_until="networkidle")
    expect(page.locator("h1")).to_be_visible()
    assert_no_horizontal_overflow(page, "mobile home")
    context.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5780")
    args = parser.parse_args()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
        page.on(
            "console",
            lambda message: errors.append(f"console: {message.text}")
            if message.type == "error"
            else None,
        )

        test_home(page, args.base_url)
        test_playlist_page(page, args.base_url)
        if errors:
            raise BrowserCheckError("; ".join(errors))
        context.close()
        test_mobile_layout(browser, args.base_url)
        browser.close()

    print("PlaylistMuse Chromium functional checks passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrowserCheckError as error:
        print(f"Browser smoke failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
