# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportMissingTypeStubs=false, reportCallIssue=false, reportAttributeAccessIssue=false, reportUnknownParameterType=false, reportMissingParameterType=false
"""Public browser demo: a recruiter talks to a Nova 2 Sonic agent over WebRTC.

Endpoints (mounted by services/api/main.py when the `demo` extra is installed):
  POST  /api/offer              SDP offer -> SDP answer (starts a bot session)
  PATCH /api/offer              trickle ICE candidates for an existing pc_id
  GET   /api/demo/idle-seconds  {"idle_seconds": float, "active": int} for auto-stop
  GET   /api/demo/report/{call_id}  200 report, 202 {"status": "live"}, or 404

Cost guards: at most DEMO_MAX_CONCURRENT new sessions, each hard-capped at
DEMO_MAX_SESSION_SECONDS. Excess offers get HTTP 503 before any AWS call.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import boto3
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    LLMRunFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.aws.nova_sonic.llm import AWSNovaSonicLLMService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import IceServer, SmallWebRTCConnection
from pipecat.transports.smallwebrtc.request_handler import (
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.workers.runner import WorkerRunner

from services.demo.metrics import (
    CallMetrics,
    ReportStore,
    persist_report,
    utc_now_iso,
)

MODEL_ID = "amazon.nova-2-sonic-v1:0"
VOICE_ID = "matthew"
AWS_REGION = os.environ.get("DEMO_AWS_REGION", "us-east-1")
MAX_CONCURRENT = 3
MAX_SESSION_SECONDS = float(os.environ.get("DEMO_MAX_SESSION_SECONDS", "300"))

SYSTEM_PROMPT = """\
You are the voice guide for VoiceAI, an open, eval-gated real-time voice-agent systems \
lab. You are speaking live with a recruiter or engineer in a browser call.
Speak English by default, or the caller's language if they switch. Use short spoken \
sentences, at most three per turn. No lists, markdown, emojis, or URLs. Open with this \
greeting: "Hi, I'm the voice guide for VoiceAI, an open, eval-gated real-time voice-agent \
stack. Would you like to hear about its purpose, its use cases, or how it works?"
Conversation style: answer the question first, with a concrete detail from the facts below. \
Never repeat the same offer twice; after most answers just stop. Only every second or third \
turn suggest ONE specific follow-up, phrased differently each time (for example how \
barge-in works, why some numbers are pending, or what the live demo runs on).
Speech recognition mishears words. When a word seems off-topic but sounds like something \
about this project (dogs for docs, gates for GATES, pipe cat for Pipecat), assume the \
project meaning, or briefly ask which they meant. If a caller asks two things, answer both.
Remember what you already said in this call. If the caller asks whether you covered a \
topic you just explained, say yes in one sentence, then ask whether they want it again or \
want to go deeper on one part. Never repeat a full explanation unless they ask for it.
Speak as someone who knows this project firsthand. Never say you are reading from docs, \
notes, a prompt or provided facts, and never mention "the facts" or "the information I \
have". If you don't know something, say naturally that you don't have that detail.
About yourself: you are the live demo agent for this project, built by Dibbayajyoti Roy \
to show the stack working. You are an AI voice agent running on AWS Bedrock Nova 2 Sonic.
The project's documentation: a README, eight verification gates, and write-ups on \
architecture, benchmarks, evaluation, the implementation plan and the runbook. Mention \
this only if the caller asks about documentation, and then give one interesting detail.
If asked about something unrelated to this project, decline in one short sentence and \
answer nothing else about it.
Stick to what you know below; never invent numbers, customers or claims.
Purpose: an open stack for real-time voice agents, covering speech-to-text, LLM \
orchestration with a typed call state machine, tools, retrieval, and text-to-speech. Every \
quality claim is built to be reproducible with a printed command.
Use cases: phone and web voice agents for public services, appointment booking, healthcare \
intake, customer support, or any telephony or voice-assistant workload. The German \
municipal phone hotline is the worked example: 24/7, 30+ languages, EU-hosted.
How it works: WebRTC or SIP/RTP audio enters a Pipecat real-time runtime with one worker \
per call. Streaming speech-to-text feeds a typed call state, then a pydantic-ai agent with \
tools, then streaming text-to-speech. Storage is PostgreSQL with pgvector, plus \
S3-compatible originals. Providers are AWS Bedrock and OpenRouter, behind protocols so \
they can be swapped without touching orchestration. Each call has one single-writer state \
machine; barge-in bumps a generation counter so stale output is dropped. Calls beyond \
capacity get a fast busy before any provider spend.
This live demo: the browser connects over WebRTC to this agent, which runs AWS Bedrock \
Nova 2 Sonic speech-to-speech on one AWS Fargate task. The task scales to zero when nobody \
calls, so the first call takes about a minute to wake it. Calls are capped at five minutes \
and three at a time to bound cost.
Measured: 58 backend tests pass, with strict Ruff and Pyright clean. A deterministic \
German voice scenario passes 11 of 11 checks. Admission control on one machine admitted 50 \
of 200 requested calls, with 150 fast busy and zero errors. That test used fake providers, \
so it measures orchestration only. The presentation site is deployed and its checks pass.
Pending, not claimed: 1,000 concurrent media calls, which needs named production hardware. \
Live Bedrock and OpenRouter smoke tests, which need credentials. Speech word error rate \
and quality scores, which need a GPU holdout evaluation. Latency figures are targets, not \
measurements: p95 caller-to-first-audio under 1.5 seconds, and p95 barge-in to silence \
under 250 milliseconds.
Benchmarks: vendor-published figures are cited as advertised, never as independent \
measurements.
Privacy: use synthetic or consented data, and keep credentials out of logs and browser \
code.
"""

_ice_servers = [IceServer(urls="stun:stun.l.google.com:19302")]
_handler = SmallWebRTCRequestHandler(ice_servers=_ice_servers)

# Live bot sessions (one asyncio task each) and offers still negotiating.
_sessions: set[asyncio.Task[None]] = set()
_pending_offers = 0
# Metrics for live calls (by pc_id) and the last finished reports.
_live: dict[str, CallMetrics] = {}
_reports = ReportStore()
# Set on connect and disconnect only; the auto-stop Lambda also checks `active`.
last_activity = time.monotonic()

router = APIRouter()


def _touch() -> None:
    global last_activity
    last_activity = time.monotonic()


async def _enforce_cap(runner: WorkerRunner) -> None:
    await asyncio.sleep(MAX_SESSION_SECONDS)
    logger.info("Demo session hit the {}s cap; stopping", MAX_SESSION_SECONDS)
    await runner.cancel(reason="session time cap")


def _boto_credentials() -> Any:
    return boto3.Session().get_credentials()


async def _aws_credentials() -> Any:
    """Explicit keys are required by the service, so resolve them via boto's chain.

    On Fargate this picks up the task role from the container credentials endpoint.
    """
    creds = await asyncio.to_thread(_boto_credentials)
    if creds is None:
        raise RuntimeError("no AWS credentials found in the boto credential chain")
    return creds.get_frozen_credentials()


class _CallTimer(FrameProcessor):
    """Passes every frame through; records speaking edges into CallMetrics."""

    def __init__(self, metrics: CallMetrics) -> None:
        super().__init__()
        self._metrics = metrics

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM:
            ts = time.monotonic()
            if isinstance(frame, UserStartedSpeakingFrame):
                self._metrics.on_user_started(ts)
            elif isinstance(frame, UserStoppedSpeakingFrame):
                self._metrics.on_user_stopped(ts)
            elif isinstance(frame, BotStartedSpeakingFrame):
                self._metrics.on_bot_started(ts)
            elif isinstance(frame, BotStoppedSpeakingFrame):
                self._metrics.on_bot_stopped(ts)
        await self.push_frame(frame, direction)


class _MeteredNovaSonic(AWSNovaSonicLLMService):
    """Keeps Nova's speech/text token split, which pipecat's LLMTokenUsage collapses."""

    def __init__(self, *, metrics: CallMetrics, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._metrics = metrics

    async def _handle_usage_event(self, event_json: Any) -> None:
        delta = event_json.get("usageEvent", {}).get("details", {}).get("delta", {})
        inp = delta.get("input", {})
        out = delta.get("output", {})
        self._metrics.add_usage(
            speech_in=inp.get("speechTokens", 0),
            text_in=inp.get("textTokens", 0),
            speech_out=out.get("speechTokens", 0),
            text_out=out.get("textTokens", 0),
        )
        await super()._handle_usage_event(event_json)


async def _run_session(conn: SmallWebRTCConnection, metrics: CallMetrics) -> None:
    runner = WorkerRunner(handle_sigint=False)
    cap: asyncio.Task[None] | None = None
    try:
        creds = await _aws_credentials()
        transport = SmallWebRTCTransport(
            webrtc_connection=conn,
            params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
        )
        llm = _MeteredNovaSonic(
            metrics=metrics,
            access_key_id=creds.access_key,
            secret_access_key=creds.secret_key,
            session_token=creds.token,
            region=AWS_REGION,
            settings=AWSNovaSonicLLMService.Settings(
                model=MODEL_ID,
                voice=VOICE_ID,
                system_instruction=SYSTEM_PROMPT,
            ),
        )
        context = LLMContext()
        pair = LLMContextAggregatorPair(context)
        pipeline = Pipeline(
            [
                transport.input(),
                pair.user(),
                llm,
                transport.output(),
                pair.assistant(),
                _CallTimer(metrics),
            ]
        )
        worker = PipelineWorker(pipeline)
        await runner.add_workers(worker)

        @transport.event_handler("on_client_connected")
        async def _on_connected(_transport: Any, _client: Any) -> None:
            metrics.on_client_connected(time.monotonic())
            # Bot greets first.
            context.add_message(
                {"role": "developer", "content": "Start by concisely introducing yourself."}
            )
            await worker.queue_frames([LLMRunFrame()])

        @transport.event_handler("on_client_disconnected")
        async def _on_disconnected(_transport: Any, _client: Any) -> None:
            await runner.cancel(reason="client disconnected")

        cap = asyncio.create_task(_enforce_cap(runner))
        await runner.run()
    except Exception:
        logger.exception("Demo session failed")
    finally:
        if cap is not None:
            cap.cancel()
        _live.pop(metrics.call_id, None)
        report = metrics.report(time.monotonic())
        _reports.put(report)
        await persist_report(report, region=AWS_REGION)
        _touch()


async def _on_connection(conn: SmallWebRTCConnection) -> None:
    # Called inside handle_web_request; must return quickly, so the session runs as a task.
    metrics = CallMetrics(
        call_id=conn.pc_id,
        started_at=utc_now_iso(),
        start_ts=time.monotonic(),
        model=MODEL_ID,
        region=AWS_REGION,
    )
    _live[conn.pc_id] = metrics
    task = asyncio.create_task(_run_session(conn, metrics))
    _sessions.add(task)
    _touch()
    task.add_done_callback(_sessions.discard)


@router.post("/api/offer")
async def offer(request: SmallWebRTCRequest) -> dict[str, str] | None:
    global _pending_offers
    if request.pc_id is not None:
        # Renegotiation of an existing connection; does not start a new session.
        return await _handler.handle_web_request(request, _on_connection)
    if len(_sessions) + _pending_offers >= MAX_CONCURRENT:
        raise HTTPException(status_code=503, detail="demo is at capacity, try again shortly")
    _pending_offers += 1
    try:
        return await _handler.handle_web_request(request, _on_connection)
    finally:
        _pending_offers -= 1


@router.patch("/api/offer")
async def patch_offer(request: SmallWebRTCPatchRequest) -> dict[str, str]:
    await _handler.handle_patch_request(request)
    return {"status": "ok"}


@router.get("/api/demo/idle-seconds")
async def idle_seconds() -> dict[str, float | int]:
    return {"idle_seconds": time.monotonic() - last_activity, "active": len(_sessions)}


@router.get("/api/demo/report/{call_id}")
async def call_report(call_id: str) -> JSONResponse:
    report = _reports.get(call_id)
    if report is not None:
        return JSONResponse(report, status_code=200)
    if call_id in _live:
        return JSONResponse({"status": "live"}, status_code=202)
    raise HTTPException(status_code=404, detail="unknown call")
