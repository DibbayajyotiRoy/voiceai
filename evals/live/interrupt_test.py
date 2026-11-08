# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportMissingTypeStubs=false, reportCallIssue=false, reportAttributeAccessIssue=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportOptionalMemberAccess=false, reportGeneralTypeIssues=false, reportMissingTypeArgument=false, reportPrivateUsage=false
"""Barge-in test v2: robust agent-speech detection before injecting the interrupt.

All timing uses one clock (wall time of inbound frame delivery, same as client.py).
Agent speech start = first instant where >=80% of the following 1.0 s of inbound
frames are above the energy threshold.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

import aiohttp
import numpy as np
import soundfile as sf
from aiortc import RTCPeerConnection, RTCSessionDescription

sys.path.insert(0, str(Path(__file__).parent))
from client import OFFER_URL, InboundRecorder, ScheduledPlayer, energy

THRESH = 0.01


def sustained_speech_start(frames, after_t, frac=0.8, win_s=1.0):
    """First t >= after_t such that >=frac of frames in [t, t+win_s] are loud."""
    ts = np.array([t for t, _ in frames])
    loud = np.array([energy(a) > THRESH for _, a in frames])
    for _i, t in enumerate(ts):
        if t < after_t:
            continue
        mask = (ts >= t) & (ts < t + win_s)
        if mask.sum() > 0 and loud[mask].mean() >= frac:
            return float(t)
    return None


async def run(out: Path) -> dict:
    wav_dir = Path(__file__).parent / "data"
    q = sf.read(str(wav_dir / "q01.wav"), dtype="int16")[0]
    interrupt = sf.read(str(wav_dir / "stop.wav"), dtype="int16")[0]
    player = ScheduledPlayer([q], gap_s=3600.0)
    recorder = InboundRecorder()
    pc = RTCPeerConnection()

    @pc.on("track")
    def on_track(track):
        if track.kind == "audio":
            asyncio.ensure_future(recorder.run(track))

    pc.addTrack(player)
    player.gate = asyncio.Event()

    @pc.on("connectionstatechange")
    def on_state():
        if pc.connectionState == "connected":
            player.gate.set()

    await pc.setLocalDescription(await pc.createOffer())
    while pc.iceGatheringState != "complete":  # noqa: ASYNC110
        await asyncio.sleep(0.05)
    async with aiohttp.ClientSession() as sess:
        async with sess.post(
            OFFER_URL,
            json={"sdp": pc.localDescription.sdp, "type": "offer"},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as res:
            answer = await res.json()
    pc_id = answer.get("pc_id", "unknown")
    await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type="answer"))
    while player._t0 is None:  # noqa: ASYNC110
        await asyncio.sleep(0.02)
    t0 = player._t0
    q_end = t0 + player.clip_ends[0]

    # wait for SUSTAINED agent speech (its answer to q01)
    t_agent_start = None
    while t_agent_start is None:
        await asyncio.sleep(0.05)
        t_agent_start = sustained_speech_start(recorder.frames, q_end + 0.1)

    # inject interrupt 2.5s into the answer
    t_intended = t_agent_start + 2.5
    player._sched.extend(
        (t_intended - t0 + n * 0.02, interrupt[i : i + 320].tobytes())
        for n, i in enumerate(range(0, len(interrupt) - 319, 320))
    )
    sent_before = player._idx
    int_end = t_intended + len(interrupt) / 16000

    # wait until agent audio stops (0.5s of continuous silence) after our interrupt
    t_stop = None
    while t_stop is None and time.time() < int_end + 25:
        await asyncio.sleep(0.05)
        frames = [(t, a) for t, a in recorder.frames if t > int_end]
        if len(frames) < 25:
            continue
        loud_ts = [t for t, a in frames if energy(a) > THRESH]
        if loud_ts:
            last_loud = max(loud_ts)
            newest = frames[-1][0]
            if newest - last_loud > 0.5:
                t_stop = last_loud
    sent_during = player._idx - sent_before
    pcm = recorder.pcm()
    sf.write(str(out / "inbound.wav"), pcm, 48000)
    with open(out / "inbound_frames.jsonl", "w") as f:  # noqa: ASYNC230
        for t, a in recorder.frames:
            f.write(json.dumps({"t": t - t0, "rms": energy(a)}) + "\n")
    await pc.close()
    return {
        "pc_id": pc_id,
        "agent_answer_start_s": round(t_agent_start - t0, 3),
        "interrupt_started_s": round(t_intended - t0, 3),
        "interrupt_ended_s": round(int_end - t0, 3),
        "interrupt_frames_sent": sent_during,
        "agent_audio_last_loud_s": round((t_stop - t0), 3) if t_stop else None,
        "interrupt_end_to_agent_stop_s": round(t_stop - int_end, 3) if t_stop else None,
    }


out = Path(__file__).parent / "data" / "interrupt4"
out.mkdir(parents=True, exist_ok=True)
stats = asyncio.run(run(out))
json.dump(stats, open(out / "interrupt.json", "w"), indent=2)
print(json.dumps(stats, indent=2))
