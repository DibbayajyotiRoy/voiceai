import json

import httpx
import pytest

from services.providers.base import ProviderError, ProviderErrorKind
from services.providers.key_registry import registry_for_tests
from services.providers.openrouter import OpenRouterSpeechProvider


async def test_stt_uses_dedicated_endpoint_and_tracks_cost() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/audio/transcriptions"
        payload = json.loads(request.content)
        assert payload["provider"] == {"zdr": True, "data_collection": "deny"}
        assert payload["input_audio"]["data"]
        return httpx.Response(200, json={"text": "Hallo", "usage": {"cost": 0.01}})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://openrouter.ai"
    )
    provider = OpenRouterSpeechProvider(
        registry=registry_for_tests(["secret"]),
        stt_model="test-stt",
        tts_model="test-tts",
        client=client,
    )
    text, usage = await provider.transcribe(b"audio", audio_format="wav", language="de")
    assert text == "Hallo"
    assert usage["cost"] == 0.01


async def test_tts_streams_raw_audio() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/audio/speech"
        return httpx.Response(200, content=b"pcm-audio")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://openrouter.ai"
    )
    provider = OpenRouterSpeechProvider(
        registry=registry_for_tests(["secret"]),
        stt_model="test-stt",
        tts_model="test-tts",
        client=client,
    )
    assert b"".join([chunk async for chunk in provider.synthesize("Hallo")]) == b"pcm-audio"


async def test_rate_limit_contains_no_response_body() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="private provider detail", headers={"Retry-After": "2"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://openrouter.ai"
    )
    provider = OpenRouterSpeechProvider(
        registry=registry_for_tests(["secret"]),
        stt_model="test-stt",
        tts_model="test-tts",
        client=client,
    )
    with pytest.raises(ProviderError) as captured:
        await provider.transcribe(b"audio", audio_format="wav", language="de")
    assert captured.value.kind is ProviderErrorKind.RATE_LIMIT
    assert captured.value.retry_after == 2
    assert "private provider detail" not in str(captured.value)
