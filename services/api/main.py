"""FastAPI service: health, metrics, per-call event log, and a WebSocket
endpoint that replays a deterministic scripted call to any connected client.

The WebSocket protocol is JSON lines:
  client -> server: {"type": "user_turn", "text": "..."}  | {"type": "ping"}
  server -> client: {"type": "assistant_turn", "text": "...", "state": {...}}
                  | {"type": "event", ...} | {"type": "pong"}

A production telephony transport (SIP/WebRTC via Pipecat) replaces this demo
transport; the orchestration behind it is identical.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import datetime
from typing import Any

from contracts.state import CallState
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from services.knowledge.embeddings import HashEmbeddingProvider
from services.knowledge.ingest import prepare_chunks, source_from_text
from services.knowledge.repository import InMemoryKnowledgeRepository, KnowledgeService
from services.observability import calls_rejected, calls_started, turn_latency
from services.orchestrator.demo import DEMO_DOC, DemoAgent
from services.orchestrator.state_machine import CallStateMachine


async def _build_knowledge() -> KnowledgeService:
    """In-process knowledge base for demo/CI (production uses Postgres+S3)."""
    source, text = source_from_text(
        document_id="buergeramt-faq",
        tenant_id="demo",
        service="buergeramt",
        version="1",
        source_uri="local://demo/buergeramt-faq.md",
        effective_from=datetime(2026, 1, 1),
        title="Bürgeramt FAQ",
        text=DEMO_DOC,
    )
    embeddings = HashEmbeddingProvider()
    repo = InMemoryKnowledgeRepository()
    await repo.publish(await prepare_chunks(source, text, embeddings))
    return KnowledgeService(repo, embeddings)


app = FastAPI(title="municipal-voiceai", version="0.1.0")

# Per-call event waterfall, newest first; bounded. This is the " Flight
# recorder" the runbook points at: when a citizen complains, dump the call.
_call_events: dict[str, list[dict[str, Any]]] = defaultdict(list)
_MAX_EVENTS_PER_CALL = 500


def _record(call_id: str, event: dict[str, Any]) -> None:
    log = _call_events[call_id]
    log.append({"ts": time.time(), **event})
    del log[:-_MAX_EVENTS_PER_CALL]


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/calls/{call_id}/events")
async def call_events(call_id: str) -> dict[str, Any]:
    return {"call_id": call_id, "events": _call_events.get(call_id, [])}


@app.websocket("/ws/call/{call_id}")
async def call_ws(websocket: WebSocket, call_id: str) -> None:
    await websocket.accept()
    machine = CallStateMachine(
        CallState(call_id=call_id, tenant_id="demo", language="de"),
        required_slots=frozenset({"street", "street_number"}),
    )
    knowledge = await _build_knowledge()
    agent = DemoAgent(machine, knowledge)
    calls_started.labels(tenant="demo").inc()
    _record(call_id, {"type": "call_started"})
    try:
        while True:
            raw = await websocket.receive_text()
            message = json.loads(raw)
            if message.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue
            if message.get("type") != "user_turn":
                await websocket.send_text(
                    json.dumps({"type": "error", "detail": "unknown message type"})
                )
                continue
            text = str(message.get("text", ""))
            started = time.perf_counter()
            _record(call_id, {"type": "user_turn", "text": text})
            await machine.append_turn("user", text)
            reply = await agent.handle(text)
            await machine.append_turn("assistant", reply)
            turn_latency.observe(time.perf_counter() - started)
            _record(call_id, {"type": "assistant_turn", "text": reply})
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "assistant_turn",
                        "text": reply,
                        "state": machine.snapshot.model_dump(mode="json"),
                    },
                    ensure_ascii=False,
                )
            )
    except WebSocketDisconnect:
        _record(call_id, {"type": "call_ended"})
    except Exception as exc:  # noqa: BLE001 - record and close cleanly
        _record(call_id, {"type": "error", "detail": repr(exc)})
        calls_rejected.labels(tenant="demo").inc()
        raise
