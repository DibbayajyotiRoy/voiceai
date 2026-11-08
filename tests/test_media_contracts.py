import pytest
from contracts.media import AudioChunk, AudioFormat
from pydantic import ValidationError


def test_pcm_20ms_contract() -> None:
    chunk = AudioChunk.pcm_20ms(call_id="call-1", sequence=0, captured_at_ns=1, data=b"\0" * 640)
    assert chunk.duration_ms == 20
    assert chunk.format is AudioFormat.PCM_S16LE


def test_pcm_20ms_rejects_wrong_size() -> None:
    with pytest.raises(ValueError, match="20 ms PCM frame"):
        AudioChunk.pcm_20ms(call_id="call-1", sequence=0, captured_at_ns=1, data=b"\0" * 100)


def test_pcm_rejects_partial_sample() -> None:
    with pytest.raises(ValidationError, match="complete 16-bit samples"):
        AudioChunk(
            call_id="call-1",
            sequence=0,
            captured_at_ns=1,
            sample_rate=16_000,
            format=AudioFormat.PCM_S16LE,
            data=b"\0",
        )
