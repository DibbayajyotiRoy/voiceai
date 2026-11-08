from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from services.providers.base import ProviderError, ProviderErrorKind


@dataclass
class _KeyState:
    alias: str
    secret: str = field(repr=False)
    max_concurrency: int = 10
    spend_cap_usd: float = 100.0
    active: int = 0
    spend_usd: float = 0.0
    failures: int = 0
    disabled: bool = False
    circuit_open_until: float = 0.0

    def available(self) -> bool:
        return (
            not self.disabled
            and self.active < self.max_concurrency
            and self.spend_usd < self.spend_cap_usd
            and time.monotonic() >= self.circuit_open_until
        )


class KeyLease:
    def __init__(self, registry: OpenRouterKeyRegistry, state: _KeyState) -> None:
        self._registry = registry
        self._state = state
        self.alias = state.alias
        self._secret = state.secret

    def client_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._secret}"}

    def pydantic_api_key(self) -> str:
        return self._secret

    def record_cost(self, amount_usd: float) -> None:
        if amount_usd < 0:
            raise ValueError("cost cannot be negative")
        self._state.spend_usd += amount_usd

    def record_success(self) -> None:
        self._state.failures = 0
        self._state.circuit_open_until = 0.0

    def record_failure(self, error: ProviderError) -> None:
        self._registry.record_failure(self._state, error)


class OpenRouterKeyRegistry:
    def __init__(self, keys: list[_KeyState], *, failure_threshold: int = 3) -> None:
        if not keys:
            raise ValueError("at least one OpenRouter key is required")
        if len({key.alias for key in keys}) != len(keys):
            raise ValueError("key aliases must be unique")
        self._keys = keys
        self._failure_threshold = failure_threshold
        self._next = 0
        self._lock = asyncio.Lock()

    @classmethod
    def from_env_names(cls, names: list[str]) -> OpenRouterKeyRegistry:
        keys: list[_KeyState] = []
        for index, env_name in enumerate(names):
            secret = os.getenv(env_name)
            if secret:
                keys.append(_KeyState(alias=f"key-{index + 1}", secret=secret))
        if not keys:
            raise ProviderError(
                ProviderErrorKind.AUTHENTICATION,
                "no configured OpenRouter key environment variables contain credentials",
            )
        return cls(keys)

    @property
    def aliases(self) -> list[str]:
        return [key.alias for key in self._keys]

    @asynccontextmanager
    async def acquire(self) -> AsyncGenerator[KeyLease]:
        async with self._lock:
            available = [key for key in self._keys if key.available()]
            if not available:
                raise ProviderError(
                    ProviderErrorKind.UNAVAILABLE,
                    "all OpenRouter keys are unavailable or at their local limits",
                )
            selected = available[self._next % len(available)]
            self._next += 1
            selected.active += 1
        try:
            yield KeyLease(self, selected)
        finally:
            async with self._lock:
                selected.active -= 1

    def record_failure(self, state: _KeyState, error: ProviderError) -> None:
        if error.kind in {ProviderErrorKind.AUTHENTICATION, ProviderErrorKind.BUDGET}:
            state.disabled = True
            return
        if error.kind is ProviderErrorKind.RATE_LIMIT:
            state.circuit_open_until = time.monotonic() + (error.retry_after or 1.0)
            return
        if error.kind in {
            ProviderErrorKind.TIMEOUT,
            ProviderErrorKind.UNAVAILABLE,
            ProviderErrorKind.STREAM,
        }:
            state.failures += 1
            if state.failures >= self._failure_threshold:
                state.circuit_open_until = time.monotonic() + 30.0


def registry_for_tests(secrets: list[str]) -> OpenRouterKeyRegistry:
    return OpenRouterKeyRegistry(
        [_KeyState(alias=f"test-{index}", secret=secret) for index, secret in enumerate(secrets)]
    )
