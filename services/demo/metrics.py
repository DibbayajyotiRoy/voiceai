# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
"""Per-call metrics for the browser demo: pure collector, report, and DynamoDB persistence.

Nothing here stores audio, transcripts, or IP addresses. Times are server-side
monotonic clock readings passed in by the caller, so the collector is testable
with synthetic timestamps.
"""

from __future__ import annotations

import asyncio
import math
import os
import time
from collections import OrderedDict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import boto3
from loguru import logger

# Nova 2 Sonic on-demand prices, USD per 1K tokens, us-east-1.
# Verified 2026-11-08 against the AWS Price List API (service AmazonBedrock, us-east-1, usage
# types USE1-NovaSonic2.0-{speech,text}-{input,output}-tokens).
PRICE_SPEECH_IN_PER_1K = 0.003
PRICE_SPEECH_OUT_PER_1K = 0.012
PRICE_TEXT_IN_PER_1K = 0.00033
PRICE_TEXT_OUT_PER_1K = 0.00275

TTL_SECONDS = 90 * 24 * 3600
MAX_STORED_REPORTS = 200


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile; values must be non-empty."""
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def _latency_summary(per_turn_ms: list[float]) -> dict[str, float | None]:
    if not per_turn_ms:
        return {"p50": None, "p95": None, "min": None, "max": None}
    return {
        "p50": round(percentile(per_turn_ms, 50), 1),
        "p95": round(percentile(per_turn_ms, 95), 1),
        "min": round(min(per_turn_ms), 1),
        "max": round(max(per_turn_ms), 1),
    }


def estimate_cost_usd(tokens: dict[str, int] | None) -> float | None:
    """Cost from real token counts only; no talk-time estimate."""
    if tokens is None:
        return None
    cost = (
        tokens["speech_in"] * PRICE_SPEECH_IN_PER_1K
        + tokens["speech_out"] * PRICE_SPEECH_OUT_PER_1K
        + tokens["text_in"] * PRICE_TEXT_IN_PER_1K
        + tokens["text_out"] * PRICE_TEXT_OUT_PER_1K
    ) / 1000
    return round(cost, 6)


class CallMetrics:
    """Collects timing from pipeline frames for one call. Timestamps are monotonic seconds."""

    def __init__(
        self, call_id: str, started_at: str, start_ts: float, model: str, region: str
    ) -> None:
        self.call_id = call_id
        self.started_at = started_at
        self.start_ts = start_ts
        self.model = model
        self.region = region
        self.connected_ts: float | None = None
        self.turns = 0
        self.interruptions = 0
        self.greeting_ms: float | None = None
        self.per_turn_ms: list[float] = []
        self.user_talk_s = 0.0
        self.agent_talk_s = 0.0
        self._user_started: float | None = None
        self._user_stopped: float | None = None
        self._bot_started: float | None = None
        self._bot_speaking = False
        self._usage: dict[str, int] | None = None

    def on_client_connected(self, ts: float) -> None:
        self.connected_ts = ts

    def on_user_started(self, ts: float) -> None:
        if self._bot_speaking:
            self.interruptions += 1
        self._user_started = ts

    def on_user_stopped(self, ts: float) -> None:
        self.turns += 1
        if self._user_started is not None:
            self.user_talk_s += ts - self._user_started
        self._user_started = None
        # Latest stop wins: the response is measured from the end of the user's last utterance.
        self._user_stopped = ts

    def on_bot_started(self, ts: float) -> None:
        self._bot_speaking = True
        self._bot_started = ts
        if self._user_stopped is not None:
            self.per_turn_ms.append((ts - self._user_stopped) * 1000)
            self._user_stopped = None
        elif self.greeting_ms is None and self.turns == 0 and self.connected_ts is not None:
            self.greeting_ms = (ts - self.connected_ts) * 1000

    def on_bot_stopped(self, ts: float) -> None:
        self._bot_speaking = False
        if self._bot_started is not None:
            self.agent_talk_s += ts - self._bot_started
        self._bot_started = None

    def add_usage(self, *, speech_in: int, speech_out: int, text_in: int, text_out: int) -> None:
        """Adds one usage delta (already incremental per event)."""
        if self._usage is None:
            self._usage = {"speech_in": 0, "speech_out": 0, "text_in": 0, "text_out": 0}
        self._usage["speech_in"] += speech_in
        self._usage["speech_out"] += speech_out
        self._usage["text_in"] += text_in
        self._usage["text_out"] += text_out

    def report(self, end_ts: float) -> dict[str, Any]:
        tokens = dict(self._usage) if self._usage is not None else None
        return {
            "call_id": self.call_id,
            "started_at": self.started_at,
            "duration_s": round(end_ts - self.start_ts, 1),
            "turns": self.turns,
            "interruptions": self.interruptions,
            "greeting_latency_ms": None if self.greeting_ms is None else round(self.greeting_ms, 1),
            "latency_ms": _latency_summary(self.per_turn_ms),
            "per_turn_ms": [round(v, 1) for v in self.per_turn_ms],
            "user_talk_s": round(self.user_talk_s, 1),
            "agent_talk_s": round(self.agent_talk_s, 1),
            "tokens": tokens,
            "est_cost_usd": estimate_cost_usd(tokens),
            "model": self.model,
            "region": self.region,
            "measured_at": "server",
        }


class ReportStore:
    """Bounded in-memory store of finished reports, oldest evicted first."""

    def __init__(self, maxsize: int = MAX_STORED_REPORTS) -> None:
        self._maxsize = maxsize
        self._items: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def put(self, report: dict[str, Any]) -> None:
        self._items[report["call_id"]] = report
        self._items.move_to_end(report["call_id"])
        while len(self._items) > self._maxsize:
            self._items.popitem(last=False)

    def get(self, call_id: str) -> dict[str, Any] | None:
        return self._items.get(call_id)


def to_dynamo(value: Any) -> Any:
    """Recursively converts floats to Decimal, which boto3 requires."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        mapping = cast("dict[str, Any]", value)
        return {k: to_dynamo(v) for k, v in mapping.items()}
    if isinstance(value, list):
        items = cast("list[Any]", value)
        return [to_dynamo(v) for v in items]
    return value


def _put_item(table_name: str, region: str, item: dict[str, Any]) -> None:
    resource: Any = cast(Any, boto3.resource)("dynamodb", region_name=region)
    table: Any = resource.Table(table_name)
    table.put_item(Item=item)


async def persist_report(report: dict[str, Any], *, region: str, now: float | None = None) -> None:
    """Writes the report plus a TTL to DEMO_CALLS_TABLE. Never raises."""
    table_name = os.environ.get("DEMO_CALLS_TABLE")
    if not table_name:
        logger.warning("DEMO_CALLS_TABLE not set; call report {} not persisted", report["call_id"])
        return
    ttl = int((time.time() if now is None else now) + TTL_SECONDS)
    item = to_dynamo({**report, "ttl": ttl})
    try:
        await asyncio.to_thread(_put_item, table_name, region, item)
    except Exception:
        logger.exception("Failed to persist call report {}", report["call_id"])


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
