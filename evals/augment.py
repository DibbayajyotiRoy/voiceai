"""Telephony augmentation: make clean studio audio sound like a phone call.

This is what makes eval numbers predictive for real lines. Chain, in order:
1. Resample to 8 kHz (PSTN band-limit) — also the codec can't carry more.
2. G.711 mu-law compansion (the actual telephony codec) via audioop.
3. Optional additive noise at a target SNR.

Everything is deterministic given a seed so an eval run is reproducible.
"""

from __future__ import annotations

import audioop
import hashlib

import numpy as np


def _rng_for(seed: str) -> np.random.Generator:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "big"))


def resample_to_telephony(pcm: np.ndarray, source_rate: int, target_rate: int = 8000) -> np.ndarray:
    """Linear-interpolation resample of float audio in [-1, 1]."""
    if source_rate == target_rate:
        return pcm
    duration = len(pcm) / source_rate
    n_target = max(1, int(round(duration * target_rate)))
    x_old = np.linspace(0.0, duration, num=len(pcm), endpoint=False)
    x_new = np.linspace(0.0, duration, num=n_target, endpoint=False)
    return np.interp(x_new, x_old, pcm)


def mulaw_roundtrip(pcm: np.ndarray) -> np.ndarray:
    """Apply G.711 mu-law encode+decode to float audio in [-1, 1]."""
    int16 = np.clip(pcm * 32767.0, -32768, 32767).astype("<i2").tobytes()
    encoded = audioop.lin2ulaw(int16, 2)
    decoded = audioop.ulaw2lin(encoded, 2)
    out = np.frombuffer(decoded, dtype="<i2").astype(np.float64) / 32768.0
    return out


def add_noise(pcm: np.ndarray, snr_db: float, seed: str) -> np.ndarray:
    """Additive white noise at the given SNR (dB), deterministic per seed."""
    if snr_db <= 0:
        raise ValueError("snr_db must be positive")
    rng = _rng_for(seed)
    noise = rng.standard_normal(len(pcm))
    signal_power = float(np.mean(pcm**2)) or 1e-12
    noise_power = float(np.mean(noise**2)) or 1e-12
    scale = np.sqrt(signal_power / (10 ** (snr_db / 10) * noise_power))
    return pcm + noise * scale


def apply_telephony_chain(
    pcm: np.ndarray,
    *,
    source_rate: int,
    snr_db: float | None = None,
    seed: str = "eval",
) -> np.ndarray:
    """Full chain: band-limit -> codec -> optional noise."""
    out = resample_to_telephony(pcm, source_rate)
    out = mulaw_roundtrip(out)
    if snr_db is not None:
        out = add_noise(out, snr_db, seed=seed)
    return out.astype(np.float32)
