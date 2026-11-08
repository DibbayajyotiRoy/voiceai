# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false
"""Evaluation runners: STT comparison, RAG retrieval, end-to-end scenarios.

Runners consume the contract protocols, so a model under test can be an
OpenRouter-hosted model, a self-hosted vLLM endpoint, or a fake for CI.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from evals.manifest import Sample
from evals.metrics import mean, recall_at_k, reciprocal_rank, wer
from services.knowledge.models import RetrievalQuery
from services.knowledge.repository import KnowledgeService
from services.providers.base import SpeechProvider


class UnavailableModelError(RuntimeError):
    """Raised when a model runner needs optional deps that are not installed."""


# ---------------------------------------------------------------------------
# STT comparison
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class STTResult:
    model: str
    sample_id: str
    scenario: str
    wer: float
    latency_ms: float


@dataclass
class STTBenchmark:
    model: str
    results: list[STTResult] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, object]:
        by_scenario: dict[str, list[float]] = {}
        for r in self.results:
            by_scenario.setdefault(r.scenario, []).append(r.wer)
        return {
            "model": self.model,
            "samples": len(self.results),
            "failures": len(self.failures),
            "wer_mean": round(mean([r.wer for r in self.results]), 4),
            "wer_p95_latency_ms": round(
                sorted([r.latency_ms for r in self.results])[
                    min(len(self.results) - 1, int(0.95 * (len(self.results) - 1)))
                ]
                if self.results
                else 0.0,
                1,
            ),
            "wer_by_scenario": {name: round(mean(v), 4) for name, v in sorted(by_scenario.items())},
        }


async def run_stt_benchmark(
    provider: SpeechProvider, model_name: str, samples: list[Sample]
) -> STTBenchmark:
    """Transcribe every sample's audio and score WER per scenario.

    Samples with no audio but a transcript are scored directly (useful for
    text-level regression and CI).
    """
    bench = STTBenchmark(model=model_name)
    for sample in samples:
        try:
            if sample.audio_path is not None:
                import soundfile as sf

                pcm, rate = sf.read(sample.audio_path, dtype="float32")
                if pcm.ndim > 1:
                    pcm = pcm.mean(axis=1)
                from evals.augment import apply_telephony_chain

                telephony = apply_telephony_chain(
                    np.asarray(pcm, dtype=np.float64), source_rate=rate, seed=sample.id
                )
                import soundfile as sf2

                wav_path = sample.audio_path.with_suffix(".telephony.wav")
                sf2.write(wav_path, telephony, 8000, subtype="PCM_16")
                started = time.perf_counter()
                text, _usage = await provider.transcribe(
                    wav_path.read_bytes(), audio_format="wav", language="de"
                )
                latency_ms = (time.perf_counter() - started) * 1000
            elif sample.transcript is not None:
                text, latency_ms = sample.transcript, 0.0
            else:
                bench.failures.append(f"{sample.id}: no audio_path or transcript")
                continue
            bench.results.append(
                STTResult(
                    model=model_name,
                    sample_id=sample.id,
                    scenario=sample.scenario,
                    wer=wer(sample.reference, text),
                    latency_ms=latency_ms,
                )
            )
        except Exception as exc:  # one bad sample must not sink the benchmark
            bench.failures.append(f"{sample.id}: {type(exc).__name__}: {exc}")
    return bench


def write_benchmark(report: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# RAG retrieval eval
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetrievalCase:
    query: str
    relevant_source_ids: set[str]


async def run_retrieval_eval(
    service: KnowledgeService, cases: list[RetrievalCase], k: int = 5
) -> dict[str, float]:
    recalls, rrs = [], []
    for case in cases:
        evidence = await service.search(
            RetrievalQuery(text=case.query, tenant_id="demo", at=datetime(2026, 6, 1), limit=k)
        )
        retrieved = [e.source_id for e in evidence]
        recalls.append(recall_at_k(case.relevant_source_ids, retrieved, k))
        rrs.append(reciprocal_rank(case.relevant_source_ids, retrieved))
    return {
        f"recall@{k}": round(mean(recalls), 4),
        "mrr": round(mean(rrs), 4),
        "cases": float(len(cases)),
    }
