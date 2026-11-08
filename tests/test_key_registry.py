import pytest

from services.providers.base import ProviderError, ProviderErrorKind
from services.providers.key_registry import OpenRouterKeyRegistry, _KeyState


async def test_keys_rotate_without_exposing_secrets() -> None:
    registry = OpenRouterKeyRegistry([_KeyState("a", "secret-a"), _KeyState("b", "secret-b")])
    async with registry.acquire() as first:
        assert first.alias == "a"
        assert first.client_headers()["Authorization"] == "Bearer secret-a"
        assert "secret-a" not in repr(first)
    async with registry.acquire() as second:
        assert second.alias == "b"


async def test_authentication_disables_only_failed_key() -> None:
    registry = OpenRouterKeyRegistry([_KeyState("a", "secret-a"), _KeyState("b", "secret-b")])
    async with registry.acquire() as lease:
        lease.record_failure(ProviderError(ProviderErrorKind.AUTHENTICATION, "denied"))
    async with registry.acquire() as lease:
        assert lease.alias == "b"


async def test_local_concurrency_limit_is_enforced() -> None:
    registry = OpenRouterKeyRegistry([_KeyState("a", "secret", max_concurrency=1)])
    async with registry.acquire():
        with pytest.raises(ProviderError, match="local limits"):
            async with registry.acquire():
                pass


async def test_spend_cap_excludes_key() -> None:
    registry = OpenRouterKeyRegistry([_KeyState("a", "secret", spend_cap_usd=0.5)])
    async with registry.acquire() as lease:
        lease.record_cost(0.5)
    with pytest.raises(ProviderError, match="local limits"):
        async with registry.acquire():
            pass
