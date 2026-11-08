# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportCallIssue=false
"""Fine-tuning data preparation for open speech models.

We don't train inside this repo's CI — training runs on the GPU box — but the
repo owns the data contract: which samples go to which model, in what format.
Runners for specific model families live behind optional deps and raise
UnavailableModelError when torch/transformers are missing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from evals.manifest import Sample, split_manifest
from evals.runners import UnavailableModelError


@dataclass(frozen=True)
class TrainingJob:
    model: str
    train_samples: int
    eval_samples: int
    output_dir: Path
    base_model: str
    hyperparameters: dict[str, object]


MODEL_RECIPES: dict[str, dict[str, object]] = {
    # STT: NVIDIA Parakeet-TDT 0.6B v3 — strong German, fast on a single GPU.
    "parakeet-tdt-0.6b-v3": {
        "base_model": "nvidia/parakeet-tdt-0.6b-v3",
        "kind": "stt",
        "hyperparameters": {"lr": 1e-5, "epochs": 3, "batch_seconds": 240},
    },
    # STT baseline: Whisper large-v3 / turbo for WER comparison.
    "whisper-large-v3-turbo": {
        "base_model": "openai/whisper-large-v3-turbo",
        "kind": "stt",
        "hyperparameters": {"lr": 1e-5, "epochs": 2, "batch_seconds": 180},
    },
    # TTS: Qwen3-TTS 0.6B — open weights, German support, cheap to serve.
    "qwen3-tts-0.6b": {
        "base_model": "Qwen/Qwen3-TTS-0.6B",
        "kind": "tts",
        "hyperparameters": {"lr": 5e-5, "epochs": 4, "batch_seconds": 120},
    },
}


def plan_training_job(model: str, samples: list[Sample], output_dir: Path) -> TrainingJob:
    """Split samples leakage-safely and emit a training plan for the model."""
    if model not in MODEL_RECIPES:
        raise KeyError(f"unknown model {model!r}; known: {sorted(MODEL_RECIPES)}")
    parts = split_manifest(samples)
    recipe = MODEL_RECIPES[model]
    return TrainingJob(
        model=model,
        train_samples=len(parts["train"]),
        eval_samples=len(parts["eval"]),
        output_dir=output_dir,
        base_model=str(recipe["base_model"]),
        hyperparameters=dict(cast("dict[str, object]", recipe["hyperparameters"])),
    )


def write_training_manifest(job: TrainingJob, samples: list[Sample], path: Path) -> None:
    """Write the train-split samples in HuggingFace datasets JSONL format."""
    parts = split_manifest(samples)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for sample in parts["train"]:
            fh.write(
                json.dumps(
                    {
                        "id": sample.id,
                        "text": sample.reference,
                        "scenario": sample.scenario,
                        **({"audio": str(sample.audio_path)} if sample.audio_path else {}),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def train_command(job: TrainingJob) -> list[str]:
    """The command a GPU box would run (requires the `speech` extras there)."""
    return [
        "python",
        "-m",
        "training.finetune",
        "--model",
        job.model,
        "--base",
        job.base_model,
        "--output",
        str(job.output_dir),
    ]


def require_speech_extras() -> None:
    try:
        import importlib

        importlib.import_module("torch")
        importlib.import_module("transformers")
    except ImportError as exc:
        raise UnavailableModelError(
            "fine-tuning requires the optional [speech] extras: uv sync --extra speech"
        ) from exc
