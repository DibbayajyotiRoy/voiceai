"""Twilio webhook, stream admission, and session startup without live provider calls."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from services.demo import bot, telephony

ACCOUNT = "AC" + "a" * 32
CALL = "CA" + "b" * 32
AUTH = "test-auth-token"
URL = f"{telephony.PUBLIC_BASE_URL}/api/telephony/incoming"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", ACCOUNT)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", AUTH)
    monkeypatch.setattr(bot, "_sessions", set())
    monkeypatch.setattr(bot, "_pending_sessions", 0)
    monkeypatch.setattr(telephony, "_pending", {})
    app = FastAPI()
    app.include_router(telephony.router)
    return TestClient(app)


def signed_request(client: TestClient, *, signature: str | None = None):
    params = {"AccountSid": ACCOUNT, "CallSid": CALL, "From": "+15550001", "To": "+15550002"}
    expected = signature or RequestValidator(AUTH).compute_signature(URL, params)
    return client.post(
        "/api/telephony/incoming", data=params, headers={"X-Twilio-Signature": expected}
    )


def test_incoming_rejects_invalid_signature_before_reservation(client: TestClient) -> None:
    response = signed_request(client, signature="invalid")
    assert response.status_code == 403
    assert telephony._pending == {}
    assert bot._pending_sessions == 0


def test_incoming_returns_stream_with_single_use_token(client: TestClient) -> None:
    response = signed_request(client)
    assert response.status_code == 200
    assert "<Connect><Stream" in response.text
    assert 'url="wss://demo-api.dibbayajyoti.com/api/telephony/ws"' in response.text
    assert 'name="session_token"' in response.text
    assert len(telephony._pending) == 1
    assert bot._pending_sessions == 1
    token = next(iter(telephony._pending))
    telephony._discard(token)
    assert bot._pending_sessions == 0


def test_incoming_at_capacity_returns_busy_without_stream(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(bot, "_sessions", {object() for _ in range(bot.MAX_CONCURRENT)})
    response = signed_request(client)
    assert response.status_code == 200
    assert "at capacity" in response.text
    assert "<Stream" not in response.text
    assert telephony._pending == {}


def test_expired_stream_token_releases_reservation(client: TestClient) -> None:
    response = signed_request(client)
    assert response.status_code == 200
    token = next(iter(telephony._pending))
    telephony._expire(token)
    assert telephony._pending == {}
    assert bot._pending_sessions == 0


def test_media_stream_rejects_unknown_token(client: TestClient) -> None:
    with client.websocket_connect("/api/telephony/ws") as websocket:
        websocket.send_json({"event": "connected"})
        websocket.send_json(
            {
                "event": "start",
                "start": {
                    "streamSid": "MZ" + "c" * 32,
                    "callSid": CALL,
                    "accountSid": ACCOUNT,
                    "customParameters": {"session_token": "unknown"},
                },
            }
        )
        closed = websocket.receive()
    assert closed["type"] == "websocket.close"
    assert closed["code"] == 1008


def test_media_stream_starts_shared_twilio_session(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = signed_request(client)
    assert response.status_code == 200
    token = next(iter(telephony._pending))
    captured: dict[str, Any] = {}

    class FakeTransport:
        def __init__(self, *, websocket: Any, params: Any) -> None:
            self.websocket = websocket
            captured["transport"] = self
            captured["params"] = params

    async def fake_run(transport: Any, metrics: Any) -> None:
        captured["metrics"] = metrics
        await transport.websocket.close()

    def fake_start(coro: Any, metrics: Any) -> asyncio.Task[None]:
        return asyncio.create_task(coro)

    monkeypatch.setattr(telephony, "FastAPIWebsocketTransport", FakeTransport)
    monkeypatch.setattr(telephony, "_run_transport_session", fake_run)
    monkeypatch.setattr(telephony, "_start_session", fake_start)

    with client.websocket_connect("/api/telephony/ws") as websocket:
        websocket.send_json({"event": "connected"})
        websocket.send_json(
            {
                "event": "start",
                "start": {
                    "streamSid": "MZ" + "c" * 32,
                    "callSid": CALL,
                    "accountSid": ACCOUNT,
                    "customParameters": {"session_token": token},
                },
            }
        )
        closed = websocket.receive()

    assert closed["type"] == "websocket.close"
    assert captured["metrics"].transport == "twilio"
    assert captured["metrics"].call_id.startswith(f"TwilioConnection-{CALL}-")
    assert captured["params"].serializer._stream_sid == "MZ" + "c" * 32
    assert telephony._pending == {}
    assert bot._pending_sessions == 0


def test_pending_expiry_timestamp_is_bounded(client: TestClient) -> None:
    response = signed_request(client)
    assert response.status_code == 200
    pending = next(iter(telephony._pending.values()))
    assert pending.expires_at <= time.monotonic() + telephony.STREAM_TOKEN_TTL_S
    telephony._expire(next(iter(telephony._pending)))
