# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false
from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models import Model

from services.providers.base import LLMEvent, LLMRequest


class PydanticAIProvider:
    def __init__(
        self,
        *,
        alias: str,
        model: Model,
        tools: Sequence[Any] = (),
        model_settings: Any = None,
    ) -> None:
        self._alias = alias
        self.model = model
        self.tools = tools
        self.model_settings = model_settings

    @property
    def alias(self) -> str:
        return self._alias

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        agent = Agent(
            self.model,
            instructions=request.instructions,
            tools=self.tools,
            retries=0,
        )
        async with agent.run_stream(
            request.prompt,
            model_settings=self.model_settings,
            timeout=request.timeout_seconds,
        ) as result:
            async for delta in result.stream_text(delta=True):
                if delta:
                    yield LLMEvent(kind="text", text=delta, provider_alias=self.alias)
            usage = result.usage
            yield LLMEvent(
                kind="usage",
                provider_alias=self.alias,
                usage={
                    "requests": usage.requests,
                    "tool_calls": usage.tool_calls,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cache_read_tokens": usage.cache_read_tokens,
                    "cache_write_tokens": usage.cache_write_tokens,
                },
            )
            yield LLMEvent(kind="completed", provider_alias=self.alias)
