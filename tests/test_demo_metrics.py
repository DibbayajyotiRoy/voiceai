"""Demo call metrics: pure collector math, report endpoint, DynamoDB writer. No AWS calls."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.demo import metrics
from services.demo.metrics import CallMetrics, percentile, to_dynamo


def _call() -> CallMetrics:
    return CallMetrics(
        call_id="pc-1",
        started_at="2026-11-08T10:00:00Z",
        start_ts=0.0,
        model="amazon.nova-2-sonic-v1:0",
        region="us-east-1",
    )


def _run_turns(m: CallMetrics, latencies_s: list[float]) -> None:
    """Each turn: user speaks 1s, stops, bot answers after the given latency."""
    t = 10.0
    for lat in latencies_s:
        m.on_user_started(t)
        m.on_user_stopped(t + 1.0)
        m.on_bot_started(t + 1.0 + lat)
        m.on_bot_stopped(t + 1.0 + lat + 2.0)
        t += 10.0


def test_percentile_nearest_rank() -> None:
    assert percentile([100.0, 200.0, 300.0, 400.0], 50) == 200.0
    assert percentile([100.0, 200.0, 300.0, 400.0], 95) == 400.0
    assert percentile([42.0], 95) == 42.0


def test_latency_p50_p95_turns_and_talk_time() -> None:
    m = _call()
    m.on_client_connected(0.0)
    m.on_bot_started(3.0)  # greeting
    m.on_bot_stopped(6.0)
    _run_turns(m, [0.5, 0.6, 0.7, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0])
    r = m.report(end_ts=200.0)

    assert r["turns"] == 10
    assert r["interruptions"] == 0
    assert r["per_turn_ms"] == [
        500.0,
        600.0,
        700.0,
        800.0,
        1000.0,
        1200.0,
        1400.0,
        1600.0,
        1800.0,
        2000.0,
    ]
    assert r["latency_ms"] == {"p50": 1000.0, "p95": 2000.0, "min": 500.0, "max": 2000.0}
    assert r["greeting_latency_ms"] == 3000.0
    assert r["user_talk_s"] == 10.0
    assert r["agent_talk_s"] == 3.0 + 2.0 * 10
    assert r["measured_at"] == "server"


def test_no_turns_gives_null_latency() -> None:
    m = _call()
    r = m.report(end_ts=5.0)
    assert r["latency_ms"] == {"p50": None, "p95": None, "min": None, "max": None}
    assert r["per_turn_ms"] == []
    assert r["greeting_latency_ms"] is None
    assert r["tokens"] is None
    assert r["est_cost_usd"] is None


def test_barge_in_counts_user_speech_while_bot_talks() -> None:
    m = _call()
    m.on_bot_started(1.0)
    m.on_user_started(2.0)  # interruption
    m.on_user_stopped(3.0)
    m.on_bot_stopped(3.5)
    m.on_user_started(10.0)  # bot silent, not an interruption
    m.on_user_stopped(11.0)
    r = m.report(end_ts=20.0)
    assert r["interruptions"] == 1
    assert r["turns"] == 2


def test_tokens_and_cost_from_real_usage_only() -> None:
    m = _call()
    m.add_usage(speech_in=1000, speech_out=2000, text_in=0, text_out=0)
    m.add_usage(speech_in=0, speech_out=0, text_in=500, text_out=1000)
    r = m.report(end_ts=1.0)
    assert r["tokens"] == {"speech_in": 1000, "speech_out": 2000, "text_in": 500, "text_out": 1000}
    expected = (
        1000 * metrics.PRICE_SPEECH_IN_PER_1K
        + 2000 * metrics.PRICE_SPEECH_OUT_PER_1K
        + 500 * metrics.PRICE_TEXT_IN_PER_1K
        + 1000 * metrics.PRICE_TEXT_OUT_PER_1K
    ) / 1000
    assert r["est_cost_usd"] == pytest.approx(expected, abs=1e-6)


def test_report_has_exact_schema_keys() -> None:
    r = _call().report(end_ts=1.0)
    assert set(r) == {
        "call_id",
        "started_at",
        "duration_s",
        "turns",
        "interruptions",
        "greeting_latency_ms",
        "latency_ms",
        "per_turn_ms",
        "user_talk_s",
        "agent_talk_s",
        "tokens",
        "est_cost_usd",
        "model",
        "region",
        "measured_at",
    }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Any]:
    from services.demo import bot

    monkeypatch.setattr(bot, "_live", {})
    monkeypatch.setattr(bot, "_reports", metrics.ReportStore(maxsize=2))
    app = FastAPI()
    app.include_router(bot.router)
    return TestClient(app), bot


def test_report_endpoint_404_unknown(client: tuple[TestClient, Any]) -> None:
    test_client, _ = client
    assert test_client.get("/api/demo/report/nope").status_code == 404


def test_report_endpoint_202_while_live(client: tuple[TestClient, Any]) -> None:
    test_client, bot = client
    bot._live["pc-live"] = _call()
    response = test_client.get("/api/demo/report/pc-live")
    assert response.status_code == 202
    assert response.json() == {"status": "live"}


def test_report_endpoint_200_after_end_and_bounded(client: tuple[TestClient, Any]) -> None:
    test_client, bot = client
    for cid in ("a", "b", "c"):
        bot._reports.put(CallMetrics(cid, "t", 0.0, "m", "r").report(end_ts=1.0))
    assert test_client.get("/api/demo/report/a").status_code == 404  # evicted, maxsize=2
    response = test_client.get("/api/demo/report/c")
    assert response.status_code == 200
    assert response.json()["call_id"] == "c"


def test_to_dynamo_converts_floats_recursively() -> None:
    item = to_dynamo({"x": 1.5, "nested": {"y": [0.25, 2, None, "s"]}, "flag": True})
    assert item == {
        "x": Decimal("1.5"),
        "nested": {"y": [Decimal("0.25"), 2, None, "s"]},
        "flag": True,
    }
    assert isinstance(item["x"], Decimal)


async def test_persist_writes_decimal_item_with_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    written: dict[str, Any] = {}

    class FakeTable:
        def put_item(self, *, Item: dict[str, Any]) -> None:  # noqa: N803
            written["item"] = Item

    class FakeResource:
        def Table(self, name: str) -> FakeTable:  # noqa: N802
            written["table"] = name
            return FakeTable()

    def fake_resource(_service: str, *, region_name: str) -> FakeResource:
        written["region"] = region_name
        return FakeResource()

    monkeypatch.setattr(metrics, "boto3", SimpleNamespace(resource=fake_resource))
    monkeypatch.setenv("DEMO_CALLS_TABLE", "demo-calls")

    report = CallMetrics("pc-9", "t", 0.0, "m", "us-east-1").report(end_ts=2.5)
    await metrics.persist_report(report, region="us-east-1", now=1_000.0)

    assert written["table"] == "demo-calls"
    assert written["region"] == "us-east-1"
    assert written["item"]["duration_s"] == Decimal("2.5")
    assert written["item"]["ttl"] == 1_000 + 90 * 24 * 3600
    assert "ip" not in str(written["item"]).lower()


async def test_persist_skips_without_table_and_swallows_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = CallMetrics("pc-0", "t", 0.0, "m", "us-east-1").report(end_ts=1.0)
    monkeypatch.delenv("DEMO_CALLS_TABLE", raising=False)
    called: list[bool] = []

    def record(*_args: object) -> None:
        called.append(True)

    monkeypatch.setattr(metrics, "_put_item", record)
    await metrics.persist_report(report, region="us-east-1")
    assert called == []

    monkeypatch.setenv("DEMO_CALLS_TABLE", "demo-calls")

    def boom(*_a: object) -> None:
        raise RuntimeError("dynamo down")

    monkeypatch.setattr(metrics, "_put_item", boom)
    await metrics.persist_report(report, region="us-east-1")  # must not raise


def test_processors_do_not_shadow_pipecat_metrics() -> None:
    # Regression: storing CallMetrics on `_metrics` replaced pipecat's own metrics
    # object, so processor setup crashed and the agent never spoke.
    from services.demo.bot import _CallTimer
    from services.demo.metrics import CallMetrics

    timer = _CallTimer(CallMetrics("x", "2026-11-08T00:00:00Z", 0.0, "m", "r"))
    assert not isinstance(timer._metrics, CallMetrics)  # noqa: SLF001
