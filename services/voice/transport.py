# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportMissingTypeStubs=false, reportCallIssue=false, reportAttributeAccessIssue=false
"""In-memory call transport for tests, local demo, and deterministic replay.

A real deployment swaps this for a WebSocket/SIP/LiveKit transport that emits
the same frames (InputAudioRawFrame downstream, consumes OutputAudioRawFrame).
The transport itself is deliberately dumb: jitter buffer, echo cancellation and
packet loss live in the media layer, not here.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    OutputAudioRawFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)

TELEPHONY_SAMPLE_RATE = 8000
PCM_CHANNELS = 1
PCM_BYTES_PER_SAMPLE = 2
CHUNK_DURATION_MS = 20
CHUNK_BYTES = (
    TELEPHONY_SAMPLE_RATE * PCM_CHANNELS * PCM_BYTES_PER_SAMPLE * CHUNK_DURATION_MS // 1000
)


class InMemoryCallTransport:
    """Queues that stand in for a phone line during one call."""

    def __init__(self, *, call_id: str, sample_rate: int = TELEPHONY_SAMPLE_RATE) -> None:
        self.call_id = call_id
        self.sample_rate = sample_rate
        self._user_audio = bytearray()
        self._user_turns: list[bytes] = []
        self._bot_audio = bytearray()
        self._closed = False
        self._bot_audio_event = asyncio.Event()

    # -- caller side (simulates the human on the phone) ---------------------

    def user_speak(self, pcm: bytes) -> None:
        """Append one utterance of 16-bit mono PCM; VAD frames are derived from it."""
        if self._closed:
            raise RuntimeError("call is closed")
        self._user_turns.append(pcm)

    def user_frames(self) -> list[Frame]:
        """Expand queued utterances into 20 ms frames bracketed by VAD events."""
        frames: list[Frame] = []
        for pcm in self._user_turns:
            frames.append(VADUserStartedSpeakingFrame())
            for offset in range(0, len(pcm), CHUNK_BYTES):
                chunk = pcm[offset : offset + CHUNK_BYTES]
                frames.append(InputAudioRawFrame(chunk, self.sample_rate, PCM_CHANNELS))
            frames.append(VADUserStoppedSpeakingFrame())
        self._user_turns.clear()
        return frames

    def vad_start(self) -> VADUserStartedSpeakingFrame:
        return VADUserStartedSpeakingFrame()

    def vad_stop(self) -> VADUserStoppedSpeakingFrame:
        return VADUserStoppedSpeakingFrame()

    # -- bot side -----------------------------------------------------------

    def bot_write(self, frame: OutputAudioRawFrame) -> None:
        self._bot_audio += frame.audio
        self._bot_audio_event.set()

    async def bot_audio(self) -> bytes:
        await self._bot_audio_event.wait()
        return bytes(self._bot_audio)

    def bot_audio_now(self) -> bytes:
        return bytes(self._bot_audio)

    async def wait_for_bot_audio(self, within: float = 5.0) -> bytes:
        async with asyncio.timeout(within):
            await self._bot_audio_event.wait()
        return bytes(self._bot_audio)

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        self._closed = True

    @property
    def user_audio(self) -> bytes:
        return bytes(self._user_audio)

    async def user_audio_chunks(self) -> AsyncIterator[bytes]:
        yield bytes(self._user_audio)
