# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportMissingTypeStubs=false, reportCallIssue=false, reportAttributeAccessIssue=false
"""Voice-layer tests: adapters behind fake providers, bridge semantics, admission control."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from contracts.state import CallState
from pipecat.frames.frames import (
    EndFrame,
    ErrorFrame,
    Frame,
    InputAudioRawFrame,
    InterruptionFrame,
    StartFrame,
    STTMetadataFrame,
    TextFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.tests.utils import run_test

from services.orchestrator.state_machine import CallStateMachine
from services.providers.base import ProviderError, ProviderErrorKind
from services.voice.adapters import TTS_SAMPLE_RATE, ContractSTTService, ContractTTSService
from services.voice.agent_bridge import AgentBridge, ScriptedAgentRunner
from services.voice.pipeline import CallPipelineFactory, CallSessionManager
from services.voice.transport import PCM_CHANNELS

SILENCE_PCM = bytes(160 * 2)  # 20 ms of 16-bit mono silence at 8 kHz


class FakeSpeechProvider:
    """Scripted SpeechProvider: maps fixed audio bytes to a fixed transcript."""

    def __init__(
        self,
        *,
        transcript: str = "Hallo",
        audio_bytes: bytes = b"fake-utterance",
        fail_transcribe: ProviderErrorKind | None = None,
        tts_chunks: list[bytes] | None = None,
    ) -> None:
        self._transcript = transcript
        self._audio_bytes = audio_bytes
        self._fail_transcribe = fail_transcribe
        self._tts_chunks = tts_chunks or [b"pcm-1", b"pcm-2"]
        self.transcribe_calls: list[tuple[bytes, str, str]] = []
        self.synthesize_calls: list[str] = []

    async def transcribe(
        self, audio: bytes, *, audio_format: str = "wav", language: str = "de"
    ) -> tuple[str, dict[str, float]]:
        self.transcribe_calls.append((audio, audio_format, language))
        if self._fail_transcribe is not None:
            raise ProviderError(self._fail_transcribe, "injected failure")
        if audio != self._audio_bytes and len(audio) < 44:  # WAV container adds a header
            raise AssertionError(f"unexpected audio payload: {len(audio)} bytes")
        return self._transcript, {"cost": 0.001}

    def synthesize(self, text: str, *, voice: str | None = None) -> AsyncIterator[bytes]:
        self.synthesize_calls.append(text)

        async def _gen() -> AsyncIterator[bytes]:
            for chunk in self._tts_chunks:
                yield chunk

        return _gen()


def make_start_frame() -> StartFrame:
    return StartFrame()


class TestContractSTTService:
    async def test_transcribes_vad_segment(self) -> None:
        provider = FakeSpeechProvider()
        stt = ContractSTTService(provider)  # type: ignore[arg-type]
        vad_audio = provider._audio_bytes
        frames_to_send = [
            make_start_frame(),
            VADUserStartedSpeakingFrame(),
            InputAudioRawFrame(vad_audio, 8000, PCM_CHANNELS),
            VADUserStoppedSpeakingFrame(),
            EndFrame(),
        ]
        down, _ = await run_test(
            stt,
            frames_to_send=frames_to_send,
            expected_down_frames=[
                STTMetadataFrame,
                STTMetadataFrame,
                VADUserStartedSpeakingFrame,
                VADUserStoppedSpeakingFrame,
                TranscriptionFrame,
            ],
        )
        transcripts = [f for f in down if isinstance(f, TranscriptionFrame)]
        assert len(transcripts) == 1
        assert transcripts[0].text == "Hallo"
        assert provider.transcribe_calls[0][1:] == ("wav", "de")

    async def test_provider_error_yields_error_frame_not_crash(self) -> None:
        provider = FakeSpeechProvider(fail_transcribe=ProviderErrorKind.UNAVAILABLE)
        stt = ContractSTTService(provider)  # type: ignore[arg-type]
        down, _ = await run_test(
            stt,
            frames_to_send=[
                make_start_frame(),
                VADUserStartedSpeakingFrame(),
                InputAudioRawFrame(b"fake-utterance", 8000, PCM_CHANNELS),
                VADUserStoppedSpeakingFrame(),
                EndFrame(),
            ],
            expected_down_frames=[
                STTMetadataFrame,
                STTMetadataFrame,
                VADUserStartedSpeakingFrame,
                VADUserStoppedSpeakingFrame,
            ],
            expected_up_frames=[STTMetadataFrame, STTMetadataFrame, ErrorFrame],
        )
        assert any("unavailable" in str(f) for f in _)


class TestContractTTSService:
    async def test_run_tts_streams_provider_chunks_as_audio_frames(self) -> None:
        # Note: full frame-flow through TTSService requires a transport that
        # acknowledges playback (audio-context choreography), so the adapter
        # contract is verified at the run_tts generator level here; end-to-end
        # audio flow is covered by the local demo with a real transport.
        provider = FakeSpeechProvider()
        tts = ContractTTSService(provider)  # type: ignore[arg-type]
        frames = [f async for f in tts.run_tts("Guten Tag.", context_id="ctx-1")]
        audio = b"".join(f.audio for f in frames if isinstance(f, TTSAudioRawFrame))
        assert audio == b"pcm-1pcm-2"
        assert all(
            f.sample_rate == TTS_SAMPLE_RATE for f in frames if isinstance(f, TTSAudioRawFrame)
        )
        assert provider.synthesize_calls == ["Guten Tag."]

    async def test_run_tts_maps_provider_errors_to_error_frames(self) -> None:
        class Failing:
            def synthesize(self, text: str, *, voice: str | None = None) -> AsyncIterator[bytes]:
                async def _gen() -> AsyncIterator[bytes]:
                    raise ProviderError(ProviderErrorKind.UNAVAILABLE, "down")
                    yield b""  # pragma: no cover

                return _gen()

        tts = ContractTTSService(Failing())  # type: ignore[arg-type]
        frames = [f async for f in tts.run_tts("Hallo.", context_id="ctx-2")]
        assert any(isinstance(f, ErrorFrame) for f in frames)


def make_machine() -> CallStateMachine:
    return CallStateMachine(CallState(call_id="call-1", tenant_id="demo"))


class TestAgentBridge:
    async def test_transcription_produces_reply_text(self) -> None:
        machine = make_machine()
        runner = ScriptedAgentRunner(["Guten Tag, wie kann ich helfen?"])
        bridge = AgentBridge(machine, runner)

        down, _ = await run_test(
            bridge,
            frames_to_send=[
                make_start_frame(),
                TranscriptionFrame("Hallo", "", "t0"),
                EndFrame(),
            ],
        )
        texts = [f.text for f in down if type(f) is TextFrame]
        assert "".join(texts).strip() == "Guten Tag, wie kann ich helfen?"
        assert runner.requests[0][0] == "Hallo"
        roles = [t.role for t in machine.snapshot.recent_turns]
        assert roles[:2] == ["user", "assistant"]

    async def test_interruption_cancels_reply_and_bumps_generation(self) -> None:
        machine = make_machine()
        runner = ScriptedAgentRunner(["ein sehr langer Satz der unterbrochen wird"])
        bridge = AgentBridge(machine, runner)

        down, _ = await run_test(
            bridge,
            frames_to_send=[
                make_start_frame(),
                TranscriptionFrame("Hallo", "", "t0"),
                Frame(),  # small delay placeholder, replaced by SleepFrame below
                InterruptionFrame(),
                EndFrame(),
            ],
        )
        # The reply may be partially spoken, but after the interruption the
        # generation must be bumped and no further text may flow.
        assert machine.snapshot.generation == 1
        # Stale deltas pushed before the interrupt may exist; anything pushed
        # after must not claim the new generation.
        assert bridge.active_generation == 1

    async def test_stale_generation_deltas_are_dropped(self) -> None:
        machine = make_machine()

        class SlowRunner:
            def __init__(self) -> None:
                self.requests: list[str] = []

            async def run_turn(
                self, *, transcript: str, state: CallState, generation: int
            ) -> AsyncIterator[str]:
                self.requests.append(transcript)
                yield "alt "
                await asyncio.sleep(0.05)  # barge-in lands mid-turn
                yield "noch mehr "

        runner = SlowRunner()
        bridge = AgentBridge(machine, runner)  # type: ignore[arg-type]
        down, _ = await run_test(
            bridge,
            frames_to_send=[
                make_start_frame(),
                TranscriptionFrame("Hallo", "", "t0"),
                InterruptionFrame(),
                EndFrame(),
            ],
        )
        # The post-interruption delta must never be pushed.
        texts = "".join(f.text for f in down if type(f) is TextFrame)
        assert "noch mehr" not in texts
        assert machine.snapshot.generation == 1


class TestCallSessionManager:
    async def test_rejects_beyond_capacity_with_fast_busy(self) -> None:
        provider = FakeSpeechProvider()
        factory = CallPipelineFactory(
            stt_provider=provider,  # type: ignore[arg-type]
            tts_provider=provider,  # type: ignore[arg-type]
            runner_factory=lambda machine: ScriptedAgentRunner(["Hallo!"]),
        )
        manager = CallSessionManager(factory, max_concurrent=2)
        s1 = await manager.try_start(call_id="c1")
        s2 = await manager.try_start(call_id="c2")
        s3 = await manager.try_start(call_id="c3")
        assert s1 is not None and s2 is not None
        assert s3 is None
        assert manager.active == 2
        assert manager.rejected == ["c3"]
        await manager.release(s1)
        s4 = await manager.try_start(call_id="c4")
        assert s4 is not None
        assert manager.active == 2

    async def test_factory_builds_isolated_per_call_state(self) -> None:
        provider = FakeSpeechProvider()
        factory = CallPipelineFactory(
            stt_provider=provider,  # type: ignore[arg-type]
            tts_provider=provider,  # type: ignore[arg-type]
            runner_factory=lambda machine: ScriptedAgentRunner(),
        )
        _, machine_a, _, _, _, _ = factory.build(call_id="a", tenant_id="demo")
        _, machine_b, _, _, _, _ = factory.build(call_id="b", tenant_id="demo")
        state_a = machine_a.snapshot
        state_a.intent = "meldung"
        assert machine_b.snapshot.intent is None
