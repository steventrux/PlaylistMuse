from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.lastfm_settings import validate_lastfm_api_key

API_KEY = "00000000000000000000000000000000"


def _client_for(status_code: int, payload: dict) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json=payload,
            request=request,
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_http_403_invalid_api_key_is_classified_as_rejected() -> None:
    async def run() -> None:
        async with _client_for(
            403,
            {
                "message": (
                    "Invalid API key - You must be granted a valid key by last.fm"
                ),
                "error": 10,
            },
        ) as client:
            with pytest.raises(ValueError, match="rejected this API key"):
                await validate_lastfm_api_key(API_KEY, client=client)

    asyncio.run(run())


def test_lastfm_service_error_remains_unavailable() -> None:
    async def run() -> None:
        async with _client_for(
            503,
            {
                "message": "Service Offline - This service is temporarily offline",
                "error": 11,
            },
        ) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await validate_lastfm_api_key(API_KEY, client=client)

    asyncio.run(run())
