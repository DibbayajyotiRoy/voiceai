# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportMissingTypeStubs=false, reportCallIssue=false, reportAttributeAccessIssue=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportPrivateUsage=false
"""Inbound Twilio phone calls connected to the shared Nova demo session."""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree

from fastapi import APIRouter, HTTPException, Request, WebSocket
from fastapi.responses import Response
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from starlette.websockets import WebSocketState
from twilio.request_validator import RequestValidator

from services.demo.bot import (
    AWS_REGION,
    MODEL_ID,
    _release_session_reservation,
    _reserve_session,
    _run_transport_session,
    _start_session,
)
from services.demo.metrics import CallMetrics, utc_now_iso

PUBLIC_BASE_URL = os.environ.get(
    "DEMO_PUBLIC_BASE_URL", "https://demo-api.dibbayajyoti.com"
).rstrip("/")
STREAM_TOKEN_TTL_S = 60
CALL_SID = re.compile(r"CA[0-9a-f]{32}")
ACCOUNT_SID = re.compile(r"AC[0-9a-f]{32}")

router = APIRouter()


@dataclass
class _PendingCall:
    call_sid: str
    account_sid: str
    expires_at: float
    timer: asyncio.TimerHandle | None = None


_pending: dict[str, _PendingCall] = {}


def _twilio_config() -> tuple[str, str]:
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not account_sid or not auth_token:
        raise HTTPException(status_code=503, detail="phone calling is not configured")
    return account_sid, auth_token


def _expire(token: str) -> None:
    if _pending.pop(token, None) is not None:
        _release_session_reservation()


def _discard(token: str) -> None:
    pending = _pending.pop(token, None)
    if pending is not None:
        if pending.timer is not None:
            pending.timer.cancel()
        _release_session_reservation()


def _busy_response() -> Response:
    response = ElementTree.Element("Response")
    ElementTree.SubElement(
        response, "Say"
    ).text = "The demo is at capacity. Please try again shortly."
    ElementTree.SubElement(response, "Hangup")
    return Response(
        ElementTree.tostring(response, encoding="unicode"), media_type="application/xml"
    )


@router.post("/api/telephony/incoming")
async def incoming(request: Request) -> Response:
    expected_account, auth_token = _twilio_config()
    form = await request.form()
    params = {key: str(value) for key, value in form.items()}
    url = f"{PUBLIC_BASE_URL}/api/telephony/incoming"
    if request.url.query:
        url = f"{url}?{request.url.query}"
    signature = request.headers.get("X-Twilio-Signature", "")
    if not RequestValidator(auth_token).validate(url, params, signature):
        raise HTTPException(status_code=403, detail="invalid Twilio signature")

    account_sid = params.get("AccountSid", "")
    call_sid = params.get("CallSid", "")
    if account_sid != expected_account or not ACCOUNT_SID.fullmatch(account_sid):
        raise HTTPException(status_code=403, detail="unexpected Twilio account")
    if not CALL_SID.fullmatch(call_sid):
        raise HTTPException(status_code=400, detail="invalid call SID")
    if not _reserve_session():
        return _busy_response()

    token = secrets.token_urlsafe(32)
    pending = _PendingCall(
        call_sid=call_sid,
        account_sid=account_sid,
        expires_at=time.monotonic() + STREAM_TOKEN_TTL_S,
    )
    pending.timer = asyncio.get_running_loop().call_later(STREAM_TOKEN_TTL_S, _expire, token)
    _pending[token] = pending
    try:
        response = ElementTree.Element("Response")
        connect = ElementTree.SubElement(response, "Connect")
        stream_url = f"{PUBLIC_BASE_URL.replace('https://', 'wss://')}/api/telephony/ws"
        stream = ElementTree.SubElement(connect, "Stream", url=stream_url)
        ElementTree.SubElement(stream, "Parameter", name="session_token", value=token)
        return Response(
            ElementTree.tostring(response, encoding="unicode"), media_type="application/xml"
        )
    except Exception:
        _discard(token)
        raise


async def _initial_start(websocket: WebSocket) -> dict[str, Any]:
    async with asyncio.timeout(10):
        connected = json.loads(await websocket.receive_text())
        if connected.get("event") != "connected":
            raise ValueError("expected Twilio connected event")
        start = json.loads(await websocket.receive_text())
        if start.get("event") != "start":
            raise ValueError("expected Twilio start event")
        return start


@router.websocket("/api/telephony/ws")
async def media_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    token = ""
    try:
        message = await _initial_start(websocket)
        start = message.get("start", {})
        custom = start.get("customParameters", {})
        token = custom.get("session_token", "")
        pending = _pending.get(token)
        if (
            pending is None
            or pending.expires_at <= time.monotonic()
            or pending.call_sid != start.get("callSid")
            or pending.account_sid != start.get("accountSid")
        ):
            if token:
                _discard(token)
            await websocket.close(code=1008)
            return
        stream_sid = start.get("streamSid", "")
        if not isinstance(stream_sid, str) or not stream_sid:
            _discard(token)
            await websocket.close(code=1008)
            return
    except (ValueError, KeyError, TypeError, TimeoutError):
        if token:
            _discard(token)
        await websocket.close(code=1008)
        return

    _pending.pop(token, None)
    if pending.timer is not None:
        pending.timer.cancel()
    try:
        _account_sid, auth_token = _twilio_config()
        serializer = TwilioFrameSerializer(
            stream_sid=stream_sid,
            call_sid=pending.call_sid,
            account_sid=pending.account_sid,
            auth_token=auth_token,
        )
        transport = FastAPIWebsocketTransport(
            websocket=websocket,
            params=FastAPIWebsocketParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                add_wav_header=False,
                serializer=serializer,
                allowed_origins=[],
            ),
        )
        metrics = CallMetrics(
            call_id=f"TwilioConnection-{pending.call_sid}-{uuid.uuid4().hex}",
            started_at=utc_now_iso(),
            start_ts=time.monotonic(),
            model=MODEL_ID,
            region=AWS_REGION,
            transport="twilio",
        )
        task = _start_session(_run_transport_session(transport, metrics), metrics)
    finally:
        _release_session_reservation()
    await task
    if websocket.application_state != WebSocketState.DISCONNECTED:
        await websocket.close()
