"""Tests for the local demo and the FastAPI service surface."""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from services.api.main import app
from services.orchestrator.demo import PASS_MARKER, run_demo


class TestLocalDemo:
    async def test_demo_passes_and_covers_hard_cases(self) -> None:
        assert await run_demo() is True

    async def test_demo_marker_constant(self) -> None:
        assert PASS_MARKER == "LOCAL_VOICE_DEMO_PASSED"  # noqa: S105


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestAPI:
    def test_health(self, client: TestClient) -> None:
        assert client.get("/health").json() == {"status": "ok"}

    def test_metrics_endpoint(self, client: TestClient) -> None:
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "voice_calls_started_total" in response.text

    def test_websocket_call_roundtrip(self, client: TestClient) -> None:
        with client.websocket_connect("/ws/call/test-call-1") as ws:
            ws.send_text(json.dumps({"type": "ping"}))
            assert json.loads(ws.receive_text())["type"] == "pong"
            ws.send_text(
                json.dumps({"type": "user_turn", "text": "Wann ist das Bürgeramt geöffnet?"})
            )
            reply = json.loads(ws.receive_text())
            assert reply["type"] == "assistant_turn"
            assert "Karl-Liebknecht" in reply["text"]
            assert reply["state"]["call_id"] == "test-call-1"

    def test_call_event_waterfall_recorded(self, client: TestClient) -> None:
        with client.websocket_connect("/ws/call/test-call-2") as ws:
            ws.send_text(json.dumps({"type": "user_turn", "text": "Hallo"}))
            ws.receive_text()
        events = client.get("/calls/test-call-2/events").json()["events"]
        kinds = [e["type"] for e in events]
        assert "call_started" in kinds
        assert "user_turn" in kinds
        assert "assistant_turn" in kinds
