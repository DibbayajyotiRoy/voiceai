"""Demo bot cost guards, tested without touching AWS or WebRTC."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

bot = pytest.importorskip("services.demo.bot")


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(bot.router)
    return TestClient(app)


def test_idle_seconds_reports_idle_and_active(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(bot, "_sessions", set())
    body = client.get("/api/demo/idle-seconds").json()
    assert body["active"] == 0
    assert body["idle_seconds"] >= 0.0


def test_idle_seconds_counts_active_sessions(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(bot, "_sessions", {object(), object()})
    assert client.get("/api/demo/idle-seconds").json()["active"] == 2


def test_offer_rejected_with_503_at_capacity_without_aws(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(bot, "_sessions", {object() for _ in range(bot.MAX_CONCURRENT)})
    monkeypatch.setattr(bot, "_pending_offers", 0)

    async def must_not_be_called(*_args, **_kwargs):
        raise AssertionError("handler reached at capacity")

    monkeypatch.setattr(bot._handler, "handle_web_request", must_not_be_called)

    response = client.post("/api/offer", json={"sdp": "v=0", "type": "offer"})
    assert response.status_code == 503


def test_pending_offers_count_toward_capacity(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(bot, "_sessions", set())
    monkeypatch.setattr(bot, "_pending_offers", bot.MAX_CONCURRENT)

    async def must_not_be_called(*_args, **_kwargs):
        raise AssertionError("handler reached at capacity")

    monkeypatch.setattr(bot._handler, "handle_web_request", must_not_be_called)

    response = client.post("/api/offer", json={"sdp": "v=0", "type": "offer"})
    assert response.status_code == 503
