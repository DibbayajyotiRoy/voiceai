from __future__ import annotations

import base64
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic_ai.models.openrouter import (
    OpenRouterModel,
    OpenRouterModelSettings,
    OpenRouterProviderConfig,
    OpenRouterUsageConfig,
)
from pydantic_ai.providers.openrouter import OpenRouterProvider

from services.providers.base import SpeechProvider, http_error
from services.providers.key_registry import KeyLease, OpenRouterKeyRegistry
from services.providers.pydantic_provider import PydanticAIProvider


def parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


class OpenRouterSpeechProvider(SpeechProvider):
    def __init__(
        self,
        *,
        registry: OpenRouterKeyRegistry,
        stt_model: str,
        tts_model: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.registry = registry
        self.stt_model = stt_model
        self.tts_model = tts_model
        self.client = client or httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1", timeout=30.0
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def transcribe(
        self, audio: bytes, *, audio_format: str, language: str
    ) -> tuple[str, dict[str, Any]]:
        async with self.registry.acquire() as lease:
            try:
                response = await self.client.post(
                    "/api/v1/audio/transcriptions",
                    headers=lease.client_headers(),
                    json={
                        "model": self.stt_model,
                        "input_audio": {
                            "data": base64.b64encode(audio).decode("ascii"),
                            "format": audio_format,
                        },
                        "language": language,
                        "provider": {"zdr": True, "data_collection": "deny"},
                    },
                )
            except httpx.TimeoutException as error:
                raise http_error(408) from error
            if response.status_code != 200:
                error = http_error(
                    response.status_code,
                    retry_after=parse_retry_after(response.headers.get("retry-after")),
                    generation_id=response.headers.get("x-generation-id"),
                )
                lease.record_failure(error)
                raise error
            payload = response.json()
            cost = payload.get("usage", {}).get("cost")
            if cost is not None:
                lease.record_cost(float(cost))
            lease.record_success()
            return payload["text"], payload.get("usage", {})

    async def synthesize(self, text: str, *, voice: str | None = None) -> AsyncIterator[bytes]:
        async with self.registry.acquire() as lease:
            try:
                async with self.client.stream(
                    "POST",
                    "/api/v1/audio/speech",
                    headers=lease.client_headers(),
                    json={
                        "model": self.tts_model,
                        "input": text,
                        "voice": voice,
                        "response_format": "pcm",
                        "provider": {"zdr": True, "data_collection": "deny"},
                    },
                ) as response:
                    if response.status_code != 200:
                        error = http_error(
                            response.status_code,
                            retry_after=parse_retry_after(response.headers.get("retry-after")),
                            generation_id=response.headers.get("x-generation-id"),
                        )
                        lease.record_failure(error)
                        raise error
                    async for chunk in response.aiter_bytes():
                        if chunk:
                            yield chunk
                lease.record_success()
            except httpx.TimeoutException as error:
                lease.record_failure(http_error(408))
                raise http_error(408) from error


def openrouter_llm(lease: KeyLease, model_name: str) -> PydanticAIProvider:
    model = OpenRouterModel(
        model_name,
        provider=OpenRouterProvider(api_key=lease.pydantic_api_key()),
        settings=OpenRouterModelSettings(
            openrouter_provider=OpenRouterProviderConfig(
                require_parameters=True,
                data_collection="deny",
                zdr=True,
                allow_fallbacks=True,
            ),
            openrouter_usage=OpenRouterUsageConfig(include=True),
        ),
    )
    return PydanticAIProvider(alias=lease.alias, model=model)
