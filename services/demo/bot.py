# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportMissingTypeStubs=false, reportCallIssue=false, reportAttributeAccessIssue=false, reportUnknownParameterType=false, reportMissingParameterType=false
"""Public browser demo: a recruiter talks to a Nova 2 Sonic agent over WebRTC.

Endpoints (mounted by services/api/main.py when the `demo` extra is installed):
  POST  /api/offer              SDP offer -> SDP answer (starts a bot session)
  PATCH /api/offer              trickle ICE candidates for an existing pc_id
  GET   /api/demo/idle-seconds  {"idle_seconds": float, "active": int} for auto-stop

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
from loguru import logger
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
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
stack. Would you like to hear about its purpose, its use cases, or how it works?" End most \
answers by offering a natural next topic.
If asked about anything unrelated to this project, decline in one sentence and offer to \
explain VoiceAI instead.
Use only the facts below. If asked about anything else, say the project docs don't cover \
it, and offer what they do cover.
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


async def _run_session(conn: SmallWebRTCConnection) -> None:
    runner = WorkerRunner(handle_sigint=False)
    cap: asyncio.Task[None] | None = None
    try:
        creds = await _aws_credentials()
        transport = SmallWebRTCTransport(
            webrtc_connection=conn,
            params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
        )
        llm = AWSNovaSonicLLMService(
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
            ]
        )
        worker = PipelineWorker(pipeline)
        await runner.add_workers(worker)

        @transport.event_handler("on_client_connected")
        async def _on_connected(_transport: Any, _client: Any) -> None:
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
        _touch()


async def _on_connection(conn: SmallWebRTCConnection) -> None:
    # Called inside handle_web_request; must return quickly, so the session runs as a task.
    task = asyncio.create_task(_run_session(conn))
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
