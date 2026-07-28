import asyncio

from backend.config import AppConfig
from backend.gemini_compat import _gemini_json_schema, _request_model


class _FakeResponse:
    is_success = True
    status_code = 200

    @staticmethod
    def json():
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": '{"title":"Test","description":"Test playlist.","tracks":[{"artist":"Artist","title":"Song","description":"Sound.","reason":"Role."}]}'
                            }
                        ]
                    }
                }
            ]
        }


class _FakeClient:
    def __init__(self):
        self.request = None

    async def post(self, url, **kwargs):
        self.request = {"url": url, **kwargs}
        return _FakeResponse()


def test_gemini_schema_removes_unsupported_string_length_keywords() -> None:
    schema = _gemini_json_schema(
        {
            "type": "object",
            "properties": {
                "title": {"type": "string", "minLength": 1, "maxLength": 100}
            },
            "required": ["title"],
        }
    )
    assert schema == {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
    }


def test_gemini_generate_content_uses_direct_structured_output_fields() -> None:
    client = _FakeClient()
    config = AppConfig(
        provider="gemini",
        api_key="AIza-test-key",
        model="gemini-3.6-flash",
    )

    result = asyncio.run(
        _request_model(
            client,
            config,
            config.model,
            "Create a test playlist.",
            5,
            exact_count=True,
        )
    )

    assert '"title":"Test"' in result
    generation_config = client.request["json"]["generationConfig"]
    assert generation_config["responseMimeType"] == "application/json"
    assert "responseJsonSchema" in generation_config
    assert "responseFormat" not in generation_config
    assert client.request["headers"]["x-goog-api-key"] == "AIza-test-key"
    assert "key=" not in client.request["url"]
