# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportMissingTypeStubs=false, reportCallIssue=false, reportAttributeAccessIssue=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportOptionalMemberAccess=false, reportGeneralTypeIssues=false, reportMissingTypeArgument=false, reportPrivateUsage=false
"""Measure voice-to-voice latency over a dialed Twilio call.

Twilio calls the agent number from TELEPHONY_EVAL_FROM_NUMBER. This process sends
prerecorded questions over the caller leg and timestamps returned agent audio at
the Twilio media boundary. It does not measure a physical handset's last mile.
"""

from __future__ import annotations

import argparse
import asyncio
import audioop
import base64
import json
import math
import os
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree

import numpy as np
import soundfile as sf
from aiohttp import WSMsgType, web
from twilio.rest import Client

SAMPLE_RATE = 8000
CHUNK_BYTES = 160
CHUNK_S = 0.02
ENERGY_THRESHOLD = 0.01


def pcm16_to_ulaw(pcm: bytes, input_rate: int = 16000) -> bytes:
    converted, _ = audioop.ratecv(pcm, 2, 1, input_rate, SAMPLE_RATE, None)
    return audioop.lin2ulaw(converted, 2)


def decode_ulaw(payload: bytes) -> np.ndarray:
    pcm = audioop.ulaw2lin(payload, 2)
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def energy(samples: np.ndarray) -> float:
    if not len(samples):
        return 0.0
    return float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def latency_summary(
    results: list[dict[str, Any]], requested_turns: int | None = None
) -> dict[str, Any]:
    values = [float(r["v2v_latency_s"]) for r in results if r.get("v2v_latency_s") is not None]
    summary: dict[str, Any] = {
        "requested_turns": len(results) if requested_turns is None else requested_turns,
        "valid_turns": len(values),
        "p50": None,
        "p95": None,
        "min": None,
        "max": None,
    }
    if values:
        summary.update(
            p50=round(percentile(values, 50), 4),
            p95=round(percentile(values, 95), 4),
            min=round(min(values), 4),
            max=round(max(values), 4),
        )
    return summary


def stream_twiml(public_ws_url: str, token: str) -> str:
    response = ElementTree.Element("Response")
    connect = ElementTree.SubElement(response, "Connect")
    stream = ElementTree.SubElement(connect, "Stream", url=public_ws_url)
    ElementTree.SubElement(stream, "Parameter", name="eval_token", value=token)
    return ElementTree.tostring(response, encoding="unicode")


class TelephonyStream:
    def __init__(self, token: str, account_sid: str) -> None:
        self.token = token
        self.account_sid = account_sid
        self.ws: web.WebSocketResponse | None = None
        self.stream_sid = ""
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()
        self.frames: list[tuple[float, np.ndarray]] = []
        self.error: str | None = None
        self.origin = time.monotonic()

    async def handle(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        try:
            async with asyncio.timeout(10):
                connected = await ws.receive_json()
                start_message = await ws.receive_json()
            start = start_message.get("start", {})
            custom = start.get("customParameters", {})
            if (
                connected.get("event") != "connected"
                or start_message.get("event") != "start"
                or custom.get("eval_token") != self.token
                or start.get("accountSid") != self.account_sid
            ):
                await ws.close(code=1008, message=b"unauthorized")
                return ws
            self.stream_sid = str(start.get("streamSid", ""))
            if not self.stream_sid:
                await ws.close(code=1008, message=b"missing stream SID")
                return ws
            self.ws = ws
            self.origin = time.monotonic()
            self.started.set()
            async for message in ws:
                if message.type == WSMsgType.TEXT:
                    data = message.json()
                    kind = data.get("event")
                    if kind == "media":
                        self._on_media(data)
                    elif kind == "stop":
                        self.stopped.set()
                        break
                elif message.type == WSMsgType.ERROR:
                    self.error = "Twilio WebSocket error"
                    break
        except Exception as exc:
            self.error = repr(exc)
            self.stopped.set()
        finally:
            self.stopped.set()
            if not ws.closed:
                await ws.close()
        return ws

    def _on_media(self, message: dict[str, Any]) -> None:
        payload = base64.b64decode(message["media"]["payload"], validate=True)
        samples = decode_ulaw(payload)
        self.frames.append((time.monotonic(), samples))

    async def wait_started(self, timeout_s: float = 30) -> None:
        async with asyncio.timeout(timeout_s):
            await self.started.wait()

    async def send_clip(self, pcm: bytes) -> float:
        if self.ws is None:
            raise RuntimeError("Twilio stream is not connected")
        payload = pcm16_to_ulaw(pcm)
        started = time.monotonic()
        for index, offset in enumerate(range(0, len(payload), CHUNK_BYTES)):
            target = started + index * CHUNK_S
            await asyncio.sleep(max(0, target - time.monotonic()))
            chunk = payload[offset : offset + CHUNK_BYTES]
            await self.ws.send_json(
                {
                    "event": "media",
                    "streamSid": self.stream_sid,
                    "media": {"payload": base64.b64encode(chunk).decode("ascii")},
                }
            )
        return time.monotonic()

    async def first_speech_after(self, timestamp: float, timeout_s: float) -> float:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.stopped.is_set():
                raise RuntimeError(self.error or "Twilio stream stopped")
            speech = [
                ts
                for ts, samples in self.frames
                if ts >= timestamp and energy(samples) > ENERGY_THRESHOLD
            ]
            if speech:
                return min(speech)
            await asyncio.sleep(0.02)
        raise TimeoutError("no agent audio before turn timeout")

    async def wait_for_silence(
        self, after: float, timeout_s: float, require_speech: bool = True
    ) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.stopped.is_set():
                raise RuntimeError(self.error or "Twilio stream stopped")
            loud = [
                ts
                for ts, samples in self.frames
                if ts >= after and energy(samples) > ENERGY_THRESHOLD
            ]
            if loud and time.monotonic() - max(loud) >= 1.0:
                return
            if not loud and not require_speech and time.monotonic() - after >= 8.0:
                return
            await asyncio.sleep(0.05)
        raise TimeoutError("agent speech did not settle")

    async def discard_greeting(self) -> None:
        started = time.monotonic()
        await self.wait_for_silence(started, timeout_s=25, require_speech=False)
        self.frames.clear()

    async def close(self) -> None:
        if self.ws is not None and not self.ws.closed:
            await self.ws.close()


def required_environment() -> tuple[str, str, str, str, str]:
    names = (
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_PHONE_NUMBER",
        "TELEPHONY_EVAL_FROM_NUMBER",
        "TELEPHONY_EVAL_PUBLIC_WS_URL",
    )
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"missing environment: {', '.join(missing)}")
    values = [os.environ[name] for name in names]
    public_url = values[-1]
    parsed = urlparse(public_url)
    if parsed.scheme != "wss" or not parsed.netloc or parsed.query:
        raise RuntimeError(
            "TELEPHONY_EVAL_PUBLIC_WS_URL must be a wss:// URL without query parameters"
        )
    return values[0], values[1], values[2], values[3], public_url


async def run(
    questions: list[str],
    wav_dir: Path,
    listen_host: str,
    listen_port: int,
    budget_s: float,
    out: Path,
) -> dict[str, Any]:
    account_sid, auth_token, agent_number, from_number, public_url = required_environment()
    clips = [sf.read(str(wav_dir / f"{question}.wav"), dtype="int16")[0] for question in questions]
    token = secrets.token_urlsafe(32)
    stream = TelephonyStream(token, account_sid)
    path = urlparse(public_url).path or "/telephony"
    app = web.Application()
    app.router.add_get(path, stream.handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, listen_host, listen_port)
    await site.start()
    client = Client(account_sid, auth_token)
    call_sid: str | None = None
    results: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "measurement_scope": "twilio_dialed_e2e",
        "transport": "twilio",
        "started_at": datetime.now(UTC).isoformat(),
        "status": "failed",
        "results": results,
    }
    try:
        created = time.monotonic()
        call = await asyncio.to_thread(
            client.calls.create,
            to=agent_number,
            from_=from_number,
            twiml=stream_twiml(public_url, token),
        )
        call_sid = str(call.sid)
        report["call_sid"] = call_sid
        report["call_create_s"] = round(time.monotonic() - created, 4)
        await stream.wait_started()
        async with asyncio.timeout(budget_s):
            await stream.discard_greeting()
            for question, clip in zip(questions, clips, strict=True):
                item: dict[str, Any] = {"question": question}
                results.append(item)
                try:
                    clip_end = await stream.send_clip(clip.tobytes())
                    first_audio = await stream.first_speech_after(clip_end, timeout_s=20)
                    item.update(
                        clip_end_s=round(clip_end - stream.origin, 4),
                        first_agent_audio_s=round(first_audio - stream.origin, 4),
                        v2v_latency_s=round(first_audio - clip_end, 4),
                    )
                    await stream.wait_for_silence(first_audio, timeout_s=30)
                except Exception as exc:
                    item["error"] = str(exc)
                    break
        report["status"] = (
            "completed"
            if len(results) == len(questions)
            and all(item.get("v2v_latency_s") is not None for item in results)
            else "failed"
        )
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        if call_sid is not None:
            try:
                final = await asyncio.to_thread(client.calls(call_sid).update, status="completed")
                report["twilio_status"] = str(final.status)
            except Exception as exc:
                report["hangup_error"] = str(exc)
        await stream.close()
        await runner.cleanup()
        write_media_artifacts(out, stream)
    report["summary"] = latency_summary(results, requested_turns=len(questions))
    return report


def write_media_artifacts(out: Path, stream: TelephonyStream) -> None:
    out.mkdir(parents=True, exist_ok=True)
    pcm = (
        np.concatenate([samples for _, samples in stream.frames])
        if stream.frames
        else np.zeros(0, dtype=np.float32)
    )
    sf.write(str(out / "inbound.wav"), pcm, SAMPLE_RATE)
    with open(out / "inbound_frames.jsonl", "w") as file:  # noqa: ASYNC230
        for timestamp, samples in stream.frames:
            file.write(json.dumps({"t": timestamp - stream.origin, "rms": energy(samples)}) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", nargs="+", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--budget", type=float, default=170.0)
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=8765)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(
        run(
            args.questions,
            Path(__file__).parent / "data",
            args.listen_host,
            args.listen_port,
            args.budget,
            out,
        )
    )
    with open(out / "client_latency.json", "w") as file:
        json.dump(report, file, indent=2)
    print(json.dumps(report["summary"], indent=2))
    print("call_sid:", report.get("call_sid"), "status:", report["status"])
    if report["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
