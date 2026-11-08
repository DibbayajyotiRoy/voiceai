"""Client-side WebRTC voice-to-voice latency measurement against the live demo.

Plays pre-recorded 16 kHz mono WAV questions in real time over an aiortc peer
connection, timestamps the last sent sample of each question and the first
received agent audio frame above an energy threshold, and records all inbound
audio to WAV for later transcription/quoting.

Usage:
  uv run python evals/live/client.py --questions q01 q02 ... --out evals/live/data/run1
"""

import argparse
import asyncio
import fractions
import json
import time
from pathlib import Path

import aiohttp
import numpy as np
import soundfile as sf
from aiortc import (
    RTCIceCandidate,
    RTCPeerConnection,
    RTCSessionDescription,
    MediaStreamError,
    MediaStreamTrack,
)
from aiortc.contrib.signaling import candidate_from_sdp
from av import AudioFrame

BASE = "https://demo-api.dibbayajyoti.com"
OFFER_URL = f"{BASE}/api/offer"
REPORT_URL = f"{BASE}/api/demo/report"


class ScheduledPlayer(MediaStreamTrack):
    """Plays a list of int16 clips (16 kHz mono) at absolute offsets, then silence."""

    kind = "audio"

    def __init__(self, clips: list[np.ndarray], gap_s: float = 1.5):
        super().__init__()
        self.gate: asyncio.Event | None = None  # set when ICE/DTLS connected
        self._sched: list[tuple[float, bytes]] = []  # (t_offset, 20ms payload)
        self.clip_ends: list[float] = []  # t offset of last sample of each clip
        off = 0.0
        for clip in clips:
            for i in range(0, len(clip) - 319, 320):
                self._sched.append((off, clip[i : i + 320].tobytes()))
                off += 0.02
            self.clip_ends.append(off)
            off += gap_s
        self.total_scheduled = off
        self._t0: float | None = None
        self._idx = 0
        self._pts = 0

    async def recv(self) -> AudioFrame:
        if self.gate is not None and not self.gate.is_set():
            await self.gate.wait()
        if self._t0 is None:
            self._t0 = time.time()
        if self._idx < len(self._sched):
            t_off, payload = self._sched[self._idx]
            wait = self._t0 + t_off - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
            self._idx += 1
        else:
            # keep the mic alive with silence after all questions
            await asyncio.sleep(0.02)
            payload = bytes(640)
        frame = AudioFrame(format="s16", layout="mono", samples=320)
        frame.planes[0].update(payload)
        frame.sample_rate = 16000
        frame.time_base = fractions.Fraction(1, 16000)
        frame.pts = self._pts
        self._pts += 320
        return frame


class InboundRecorder:
    def __init__(self) -> None:
        self.frames: list[tuple[float, np.ndarray]] = []  # (wall time, float32 mono)
        self._origin: int | None = None  # first RTP pts
        self._chunks: dict[int, np.ndarray] = {}  # sample offset -> pcm

    async def run(self, track: MediaStreamError | MediaStreamTrack) -> None:
        try:
            while True:
                frame = await track.recv()
                arr = frame.to_ndarray().reshape(-1).astype(np.float32) / 32768.0
                self.frames.append((time.time(), arr))
                pts = int(frame.pts) if frame.pts is not None else None
                if pts is not None:
                    if self._origin is None:
                        self._origin = pts
                    off = pts - self._origin
                    self._chunks[off] = arr
        except MediaStreamError:
            pass

    def pcm(self) -> np.ndarray:
        """Content-aligned timeline built from RTP pts (silence-filled gaps)."""
        if not self._chunks:
            return np.zeros(0, dtype=np.float32)
        offs = sorted(self._chunks)
        end = max(offs + [o + len(c) for o, c in self._chunks.items()])
        out = np.zeros(end, dtype=np.float32)
        for o, c in self._chunks.items():
            if o + len(c) <= end:
                out[o : o + len(c)] = c
        return out


def energy(arr: np.ndarray) -> float:
    return float(np.sqrt(np.mean(arr.astype(np.float64) ** 2))) if len(arr) else 0.0


async def run(questions: list[str], wav_dir: Path, out: Path, call_budget_s: float) -> dict:
    clips = [sf.read(str(wav_dir / f"{q}.wav"), dtype="int16")[0] for q in questions]
    player = ScheduledPlayer(clips)
    pc = RTCPeerConnection()
    recorder = InboundRecorder()

    @pc.on("track")
    def on_track(track: MediaStreamTrack) -> None:
        if track.kind == "audio":
            asyncio.ensure_future(recorder.run(track))

    pc.addTrack(player)
    player.gate = asyncio.Event()

    @pc.on("connectionstatechange")
    def on_state() -> None:
        if pc.connectionState == "connected":
            player.gate.set()

    await pc.setLocalDescription(await pc.createOffer())
    # wait for ICE gathering
    while pc.iceGatheringState != "complete":
        await asyncio.sleep(0.05)
    t_offer = time.time()
    async with aiohttp.ClientSession() as sess:
        async with sess.post(
            OFFER_URL,
            json={"sdp": pc.localDescription.sdp, "type": "offer"},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as res:
            answer = await res.json()
    t_answer = time.time()
    pc_id = answer.get("pc_id", "unknown")
    await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type="answer"))

    t0 = None
    while t0 is None:
        await asyncio.sleep(0.02)
        t0 = player._t0  # absolute clock anchor for clip end times
    clip_ends_abs = [t0 + e for e in player.clip_ends]

    # analyse inbound energy in 20 ms windows against clip timeline
    results = []
    t_call_end = t_offer + call_budget_s
    spoken_idx = 0
    last_log = 0.0
    while time.time() < t_call_end and spoken_idx < len(questions):
        await asyncio.sleep(0.05)
        # find first question whose agent response has started
        if spoken_idx < len(clip_ends_abs) and time.time() > clip_ends_abs[spoken_idx] + 0.05:
            # scan recorder frames received after clip end for energy
            thresh = 0.01
            cand = [
                (t, energy(a))
                for t, a in recorder.frames
                if t >= clip_ends_abs[spoken_idx] and energy(a) > thresh
            ]
            if cand:
                t_first = cand[0][0]
                results.append(
                    {
                        "question": questions[spoken_idx],
                        "clip_end_s": clip_ends_abs[spoken_idx] - t_offer,
                        "first_agent_audio_s": t_first - t_offer,
                        "v2v_latency_s": t_first - clip_ends_abs[spoken_idx],
                    }
                )
                spoken_idx += 1

    # dump raw inbound audio (decoded opus runs at 48 kHz)
    pcm = recorder.pcm()
    sf.write(str(out / "inbound.wav"), pcm, 48000)
    with open(out / "inbound_frames.jsonl", "w") as f:
        for t, a in recorder.frames:
            f.write(json.dumps({"t": t - t_offer, "rms": energy(a)}) + "\n")
    await pc.close()
    return {"pc_id": pc_id, "offer_rtt_s": t_answer - t_offer, "results": results}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--budget", type=float, default=170.0)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stats = asyncio.run(run(args.questions, Path(__file__).parent / "data", out, args.budget))
    with open(out / "client_latency.json", "w") as f:
        json.dump(stats, f, indent=2)
    for r in stats["results"]:
        print(f'{r["question"]}: v2v={r["v2v_latency_s"]:.2f}s')
    print("pc_id:", stats["pc_id"], "offer_rtt:", round(stats["offer_rtt_s"], 2))


if __name__ == "__main__":
    main()
