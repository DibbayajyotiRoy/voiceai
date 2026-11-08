from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AudioFormat(StrEnum):
    PCM_S16LE = "pcm_s16le"
    PCMA = "pcma"
    PCMU = "pcmu"
    OPUS = "opus"


class AudioChunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    call_id: str = Field(min_length=1, max_length=128)
    sequence: int = Field(ge=0)
    captured_at_ns: int = Field(ge=0)
    sample_rate: int = Field(gt=0, le=192_000)
    channels: Literal[1] = 1
    format: AudioFormat
    data: bytes = Field(min_length=1)

    @model_validator(mode="after")
    def validate_pcm(self) -> AudioChunk:
        if self.format is AudioFormat.PCM_S16LE and len(self.data) % 2:
            raise ValueError("PCM_S16LE data must contain complete 16-bit samples")
        return self

    @property
    def duration_ms(self) -> float:
        if self.format is AudioFormat.PCM_S16LE:
            return len(self.data) / 2 * 1000 / self.sample_rate
        raise ValueError("Compressed audio duration requires a codec-specific decoder")

    @classmethod
    def pcm_20ms(
        cls,
        *,
        call_id: str,
        sequence: int,
        captured_at_ns: int,
        sample_rate: int = 16_000,
        data: bytes,
    ) -> AudioChunk:
        expected_bytes = sample_rate // 50 * 2
        if len(data) != expected_bytes:
            raise ValueError(f"20 ms PCM frame requires {expected_bytes} bytes")
        return cls(
            call_id=call_id,
            sequence=sequence,
            captured_at_ns=captured_at_ns,
            sample_rate=sample_rate,
            format=AudioFormat.PCM_S16LE,
            data=data,
        )


class TranscriptChunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    call_id: str = Field(min_length=1, max_length=128)
    turn_id: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=0)
    text: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    is_final: bool = False
    generation: int = Field(ge=0)


class TextClause(BaseModel):
    model_config = ConfigDict(frozen=True)

    call_id: str
    turn_id: str
    generation: int = Field(ge=0)
    text: str = Field(min_length=1)
    is_final: bool = False
