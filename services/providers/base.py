from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class ProviderErrorKind(StrEnum):
    AUTHENTICATION = "authentication"
    BUDGET = "budget"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"
    STREAM = "stream"


class ProviderError(RuntimeError):
    def __init__(
        self,
        kind: ProviderErrorKind,
        message: str,
        *,
        status: int | None = None,
        retry_after: float | None = None,
        generation_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.retry_after = retry_after
        self.generation_id = generation_id


@dataclass(frozen=True)
class LLMRequest:
    instructions: str
    prompt: str
    call_id: str
    turn_id: str
    generation: int
    timeout_seconds: float = 20.0


_EMPTY_USAGE: Callable[[], dict[str, int]] = dict


@dataclass(frozen=True)
class LLMEvent:
    kind: str
    text: str = ""
    usage: Mapping[str, int] = field(default_factory=_EMPTY_USAGE)  # pyright: ignore[reportUnknownVariableType]
    provider_alias: str = ""


class LLMProvider(Protocol):
    @property
    def alias(self) -> str: ...

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]: ...


class SpeechProvider(Protocol):
    async def transcribe(
        self, audio: bytes, *, audio_format: str, language: str
    ) -> tuple[str, dict[str, Any]]: ...

    def synthesize(self, text: str, *, voice: str | None = None) -> AsyncIterator[bytes]: ...


def http_error(
    status: int, *, retry_after: float | None = None, generation_id: str | None = None
) -> ProviderError:
    kinds = {
        401: ProviderErrorKind.AUTHENTICATION,
        403: ProviderErrorKind.AUTHENTICATION,
        402: ProviderErrorKind.BUDGET,
        429: ProviderErrorKind.RATE_LIMIT,
        408: ProviderErrorKind.TIMEOUT,
        504: ProviderErrorKind.TIMEOUT,
    }
    kind = kinds.get(
        status,
        ProviderErrorKind.UNAVAILABLE if status >= 500 else ProviderErrorKind.INVALID,
    )
    return ProviderError(
        kind,
        f"provider returned HTTP {status}",
        status=status,
        retry_after=retry_after,
        generation_id=generation_id,
    )
