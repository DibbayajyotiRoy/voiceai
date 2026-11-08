"""Manifest-driven evaluation datasets with leakage-safe splitting.

A manifest is a JSONL file where each line is one sample:
    {
      "id": "stt-0001",
      "audio_path": "data/audio/stt-0001.wav",   # or "transcript" for text-level samples
      "reference": "Mein Name ist Müller",
      "scenario": "street_name" | "dictated_number" | "name_spelling" | "smalltalk",
      "speaker_group": "speaker-17",             # split unit: all samples of a
      ...                                        # speaker stay in one split
    }

Splits are assigned by hashing the speaker group, never the sample id, so a
speaker (and their street names/accents) cannot leak across train/eval.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Sample:
    id: str
    reference: str
    scenario: str
    speaker_group: str
    audio_path: Path | None
    transcript: str | None
    extra: dict[str, Any]


def load_manifest(path: Path) -> list[Sample]:
    samples: list[Sample] = []
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            try:
                samples.append(
                    Sample(
                        id=raw["id"],
                        reference=raw["reference"],
                        scenario=raw.get("scenario", "general"),
                        speaker_group=raw.get("speaker_group", raw["id"]),
                        audio_path=Path(raw["audio_path"]) if raw.get("audio_path") else None,
                        transcript=raw.get("transcript"),
                        extra={k: v for k, v in raw.items() if k not in _KNOWN_KEYS},
                    )
                )
            except KeyError as exc:
                raise ValueError(f"{path}:{line_no}: missing field {exc}") from exc
    return samples


_KNOWN_KEYS = {"id", "reference", "scenario", "speaker_group", "audio_path", "transcript"}


def assign_split(speaker_group: str, splits: dict[str, float]) -> str:
    """Deterministically assign a speaker group to a split by hash.

    splits: {"train": 0.7, "eval": 0.15, "test": 0.15} — values are cumulative weights.
    """
    digest = hashlib.sha256(speaker_group.encode("utf-8")).hexdigest()
    draw = int(digest[:12], 16) / 16**12
    cumulative = 0.0
    for name, weight in splits.items():
        cumulative += weight
        if draw < cumulative:
            return name
    return next(reversed(splits))


def split_manifest(
    samples: list[Sample], splits: dict[str, float] | None = None
) -> dict[str, list[Sample]]:
    splits = splits or {"train": 0.7, "eval": 0.15, "test": 0.15}
    out: dict[str, list[Sample]] = {name: [] for name in splits}
    for sample in samples:
        out[assign_split(sample.speaker_group, splits)].append(sample)
    return out


def check_no_leakage(parts: dict[str, list[Sample]]) -> None:
    """Assert speaker groups are disjoint across splits."""
    seen: dict[str, str] = {}
    for split, samples in parts.items():
        for s in samples:
            owner = seen.setdefault(s.speaker_group, split)
            if owner != split:
                raise AssertionError(
                    f"speaker group {s.speaker_group!r} leaks across {owner!r} and {split!r}"
                )
