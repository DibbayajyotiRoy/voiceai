# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportMissingTypeStubs=false, reportCallIssue=false, reportAttributeAccessIssue=false
"""Pipecat service adapters that expose a contract-level SpeechProvider to the pipeline.

STT: a SegmentedSTTService that hands each VAD-delimited utterance (as WAV, since
HTTP STT endpoints expect a container) to SpeechProvider.transcribe.
TTS: a TTSService that streams SpeechProvider.synthesize chunks as TTSAudioRawFrame.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from loguru import logger
from pipecat.frames.frames import ErrorFrame, Frame, TranscriptionFrame, TTSAudioRawFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.services.tts_service import TTSService
from pipecat.utils.time import time_now_iso8601

from services.providers.base import ProviderError, SpeechProvider

TELEPHONY_SAMPLE_RATE = 8000
PCM_CHANNELS = 1
PCM_BYTES_PER_SAMPLE = 2
TTS_SAMPLE_RATE = 24000


class ContractSTTService(SegmentedSTTService):
    """Utterance-based STT backed by any SpeechProvider (OpenRouter, self-hosted, …)."""

    def __init__(
        self,
        provider: SpeechProvider,
        *,
        language: str = "de",
        sample_rate: int = 8000,
        trailing_silence_secs: float = 0.0,
    ) -> None:
        super().__init__(
            sample_rate=sample_rate,
            trailing_silence_secs=trailing_silence_secs,
            audio_passthrough=False,
        )
        self._provider = provider
        self._language = language
        self.transcribed_segments: list[bytes] = []

    @property
    def wants_wav_segments(self) -> bool:
        # HTTP STT endpoints take an uploaded audio container, not raw PCM.
        return True

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        try:
            text, _usage = await self._provider.transcribe(
                audio, audio_format="wav", language=self._language
            )
        except ProviderError as exc:
            logger.warning("STT provider error kind={}: {}", exc.kind, exc)
            yield ErrorFrame(error=f"stt provider error: {exc.kind}")
            return
        except Exception as exc:  # defensive: never kill the call on STT failure
            logger.exception("Unexpected STT failure")
            yield ErrorFrame(error=f"stt failure: {type(exc).__name__}")
            return
        self.transcribed_segments.append(audio)
        if not text:
            return
        yield TranscriptionFrame(text, self._user_id, time_now_iso8601())


class ContractTTSService(TTSService):
    """Streaming TTS backed by any SpeechProvider; yields raw PCM audio frames."""

    def __init__(self, provider: SpeechProvider, *, voice: str | None = None) -> None:
        super().__init__(
            sample_rate=TTS_SAMPLE_RATE,
            push_start_frame=True,
            push_stop_frames=True,
            settings=TTSSettings(model=None, voice=voice, language="de"),
        )
        self._provider = provider
        self._voice = voice
        self.synthesized_texts: list[str] = []

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        self.synthesized_texts.append(text)
        try:
            async for chunk in self._provider.synthesize(text, voice=self._voice):
                if not chunk:
                    continue
                yield TTSAudioRawFrame(chunk, TTS_SAMPLE_RATE, PCM_CHANNELS, context_id=context_id)
        except ProviderError as exc:
            logger.warning("TTS provider error kind={}: {}", exc.kind, exc)
            yield ErrorFrame(error=f"tts provider error: {exc.kind}")
        except Exception as exc:
            logger.exception("Unexpected TTS failure")
            yield ErrorFrame(error=f"tts failure: {type(exc).__name__}")
