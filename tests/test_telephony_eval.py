"""Telephony eval codec, timing, failure, summary, and artifact checks."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf

from evals.live import telephony


def test_pcm16_to_ulaw_uses_20ms_packets() -> None:
    pcm = (np.sin(np.arange(320) / 10) * 10000).astype(np.int16).tobytes()
    payload = telephony.pcm16_to_ulaw(pcm)
    assert len(payload) == 160
    decoded = telephony.decode_ulaw(payload)
    assert len(decoded) == 160
    assert telephony.energy(decoded) > telephony.ENERGY_THRESHOLD


def test_stream_twiml_is_bidirectional_and_carries_token() -> None:
    twiml = telephony.stream_twiml("wss://example.test/telephony", "random-token")
    assert twiml.startswith("<Response><Connect><Stream")
    assert 'url="wss://example.test/telephony"' in twiml
    assert 'name="eval_token" value="random-token"' in twiml


def test_latency_summary_counts_25_valid_turns() -> None:
    results = [{"v2v_latency_s": value / 1000} for value in range(1, 26)]
    summary = telephony.latency_summary(results)
    assert summary == {
        "requested_turns": 25,
        "valid_turns": 25,
        "p50": 0.013,
        "p95": 0.024,
        "min": 0.001,
        "max": 0.025,
    }


def test_latency_summary_keeps_failures_visible() -> None:
    results = [{"v2v_latency_s": 1.0}, {"question": "q02", "error": "timeout"}]
    summary = telephony.latency_summary(results, requested_turns=15)
    assert summary["requested_turns"] == 15
    assert summary["valid_turns"] == 1
    assert summary["p50"] == 1.0


async def test_send_clip_paces_and_timestamps_final_chunk() -> None:
    stream = telephony.TelephonyStream("token", "account")

    class FakeWS:
        def __init__(self) -> None:
            self.messages: list[dict[str, Any]] = []

        async def send_json(self, message: dict[str, Any]) -> None:
            self.messages.append(message)

    ws = FakeWS()
    stream.ws = ws
    stream.stream_sid = "MZ-test"
    pcm = np.zeros(640, dtype=np.int16).tobytes()
    started = time.monotonic()
    clip_end = await stream.send_clip(pcm)
    assert clip_end - started >= 0.015
    assert len(ws.messages) == 2
    assert all(message["event"] == "media" for message in ws.messages)
    assert all(message["streamSid"] == "MZ-test" for message in ws.messages)


async def test_first_speech_ignores_silence_and_old_frames() -> None:
    stream = telephony.TelephonyStream("token", "account")
    now = time.monotonic()
    loud = np.full(160, 0.2, dtype=np.float32)
    quiet = np.zeros(160, dtype=np.float32)
    stream.frames = [(now - 1, loud), (now + 0.01, quiet), (now + 0.02, loud)]
    first = await stream.first_speech_after(now, timeout_s=0.2)
    assert first == now + 0.02


async def test_first_speech_times_out_without_audio() -> None:
    stream = telephony.TelephonyStream("token", "account")
    with pytest.raises(TimeoutError, match="no agent audio"):
        await stream.first_speech_after(time.monotonic(), timeout_s=0.01)


def test_media_artifacts_include_wav_and_frame_timeline(tmp_path: Path) -> None:
    stream = telephony.TelephonyStream("token", "account")
    stream.origin = 10.0
    stream.frames = [(10.02, np.full(160, 0.1, dtype=np.float32))]
    telephony.write_media_artifacts(tmp_path, stream)
    samples, rate = sf.read(str(tmp_path / "inbound.wav"))
    assert rate == 8000
    assert len(samples) == 160
    row = json.loads((tmp_path / "inbound_frames.jsonl").read_text())
    assert row["t"] == pytest.approx(0.02)
    assert row["rms"] > telephony.ENERGY_THRESHOLD


def test_required_environment_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_PHONE_NUMBER",
        "TELEPHONY_EVAL_FROM_NUMBER",
        "TELEPHONY_EVAL_PUBLIC_WS_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="missing environment"):
        telephony.required_environment()


def test_combiner_aggregates_runs_and_rejects_missing_turns() -> None:
    from evals.live.telephony_report import combine_reports

    first = {
        "call_sid": "CA1",
        "summary": {"requested_turns": 2},
        "results": [{"v2v_latency_s": 1.0}, {"v2v_latency_s": 1.2}],
    }
    second = {
        "call_sid": "CA2",
        "summary": {"requested_turns": 2},
        "results": [{"v2v_latency_s": 1.1}, {"error": "timeout"}],
    }
    combined = combine_reports([first, second])
    assert combined["runs"] == ["CA1", "CA2"]
    assert combined["summary"]["requested_turns"] == 4
    assert combined["summary"]["valid_turns"] == 3
    assert combined["summary"]["p50"] == 1.1
    assert combined["status"] == "failed"
