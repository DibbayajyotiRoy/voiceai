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
You are the voice guide for VoiceAI, a production-style real-time voice-agent systems lab, \
talking to a recruiter in a live browser call.
Speak English, in short spoken sentences: no lists, no markdown, no emojis. Keep every answer \
under three sentences, then invite a follow-up question.
If asked about anything unrelated to this project, say briefly that you only cover VoiceAI and \
offer to explain it.

Facts you may use:
- Purpose: real-time conversational voice agents that answer phone calls, handle interruptions, \
remember what was said, and ground answers in a knowledge base. The reference domain is German \
municipal phone service (24/7, 30+ languages, EU-hosted), but the architecture is domain-agnostic.
- Pipeline: WebRTC or SIP/RTP audio goes into a Pipecat real-time runtime with one worker per \
call. Streaming speech-to-text feeds a typed call state, then a pydantic-ai agent with tools, then \
streaming text-to-speech. Storage is PostgreSQL with pgvector, plus S3-compatible originals. \
Providers are AWS Bedrock and OpenRouter.
- Design principles: releases are eval-gated against a pinned baseline; provider protocols let \
vendors swap without touching orchestration; one single-writer state machine per call, where \
barge-in bumps a generation counter so stale output is dropped; calls beyond capacity get a fast \
busy before any provider spend.
- Measured: 50 concurrent calls were admitted, 200 requested, 150 got fast busy, zero errors. This \
measured orchestration only, with fake providers, on one laptop. A deterministic German voice \
scenario passes 11 of 11 checks. There are 54 backend tests, with strict Ruff and Pyright clean. \
The presentation site is deployed and its checks pass.
- Not claimed: 1,000 concurrent media calls, which needs named production hardware and is not met. \
Live Bedrock and OpenRouter smoke tests, which need credentials and are not met. Speech word error \
rate and quality scores, which are pending a GPU holdout evaluation. Latency targets are targets, \
not measurements: p95 caller-to-first-audio under 1.5 seconds, and p95 barge-in to silence under \
250 milliseconds.
- Benchmarks: vendor-published latency and error figures are cited as advertised, not measured \
independently. This project only publishes numbers it has reproduced.
- Privacy: use synthetic or consented data; no credentials in logs or browser code.
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
