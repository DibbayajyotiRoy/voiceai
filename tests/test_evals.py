"""Evals tests: metrics, leakage-safe splits, augmentation, scenarios, load harness."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from contracts.state import CallState

from evals.augment import apply_telephony_chain, mulaw_roundtrip, resample_to_telephony
from evals.manifest import Sample, assign_split, check_no_leakage, load_manifest, split_manifest
from evals.metrics import normalize_german, percentile, repetition_detected, wer
from evals.runners import RetrievalCase, run_retrieval_eval, run_stt_benchmark
from evals.scenarios import Expectation, Scenario, run_scenario
from loadtest.harness import run_load
from services.knowledge.embeddings import HashEmbeddingProvider
from services.knowledge.ingest import prepare_chunks, source_from_file
from services.knowledge.repository import InMemoryKnowledgeRepository, KnowledgeService
from services.orchestrator.state_machine import CallStateMachine


class TestGermanNormalization:
    def test_digits_expand_to_number_words(self) -> None:
        assert normalize_german("Bergmannstraße 24") == "bergmannstrasse vierundzwanzig"

    def test_case_punctuation_fold(self) -> None:
        assert normalize_german("Müller, Hans!") == "müller hans"

    def test_wer_perfect_and_substitution(self) -> None:
        assert wer("Hallo Welt", "Hallo Welt") == 0.0
        assert wer("Hallo Welt", "Hallo Thor") == 0.5

    def test_wer_dictated_number_matches_written_digits(self) -> None:
        # Reference written as digits, hypothesis dictated as words -> 0 WER.
        assert wer("Die 24 ist betroffen", "die vierundzwanzig ist betroffen") == 0.0

    def test_percentile(self) -> None:
        assert percentile([1, 2, 3, 4], 50) == 2.5
        assert percentile([], 95) == 0.0


class TestManifestSplits:
    def _samples(self) -> list[Sample]:
        return [
            Sample(
                id=f"{spkr}-{i}",
                reference=f"Text {i}",
                scenario="street_name",
                speaker_group=spkr,
                audio_path=None,
                transcript=f"Text {i}",
                extra={},
            )
            for spkr in ("speaker-a", "speaker-b", "speaker-c")
            for i in range(3)
        ]

    def test_speaker_groups_do_not_leak(self) -> None:
        parts = split_manifest(self._samples())
        check_no_leakage(parts)

    def test_assignment_is_deterministic(self) -> None:
        assert assign_split("speaker-x", {"train": 0.5, "test": 0.5}) == assign_split(
            "speaker-x", {"train": 0.5, "test": 0.5}
        )

    def test_load_manifest_roundtrip(self, tmp_path: Path) -> None:
        path = tmp_path / "m.jsonl"
        path.write_text(
            '{"id": "s1", "reference": "Hallo", "speaker_group": "g1", "transcript": "Hallo"}\n',
            encoding="utf-8",
        )
        samples = load_manifest(path)
        assert samples[0].id == "s1" and samples[0].scenario == "general"

    def test_load_manifest_missing_field_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.jsonl"
        path.write_text('{"id": "s1"}\n', encoding="utf-8")
        with pytest.raises(ValueError, match="missing field"):
            load_manifest(path)


class TestTelephonyAugmentation:
    def test_resample_48k_to_8k(self) -> None:
        pcm = np.sin(2 * np.pi * 440 * np.arange(48000) / 48000)
        out = resample_to_telephony(pcm, 48000)
        assert len(out) == 8000

    def test_mulaw_is_deterministic_and_bounded(self) -> None:
        pcm = np.linspace(-1, 1, 1000)
        a, b = mulaw_roundtrip(pcm), mulaw_roundtrip(pcm)
        np.testing.assert_array_equal(a, b)
        assert np.max(np.abs(a)) <= 1.0

    def test_chain_deterministic_per_seed(self) -> None:
        pcm = np.random.default_rng(1).standard_normal(8000) * 0.1
        a = apply_telephony_chain(pcm, source_rate=8000, snr_db=20, seed="call-1")
        b = apply_telephony_chain(pcm, source_rate=8000, snr_db=20, seed="call-1")
        np.testing.assert_array_equal(a, b)
        c = apply_telephony_chain(pcm, source_rate=8000, snr_db=20, seed="call-2")
        assert not np.array_equal(a, c)


class FakeSTT:
    def __init__(self, transcript: str) -> None:
        self._transcript = transcript

    async def transcribe(
        self, audio: bytes, *, audio_format: str = "wav", language: str = "de"
    ) -> tuple[str, dict[str, float]]:
        return self._transcript, {"cost": 0.0}


class TestSTTBenchmark:
    async def test_scores_transcript_samples(self) -> None:
        samples = [
            Sample(
                id="s1",
                reference="Mein Name ist Müller",
                scenario="name",
                speaker_group="g1",
                audio_path=None,
                transcript="Mein Name ist Müller",
                extra={},
            ),
            Sample(
                id="s2",
                reference="Die 12 ist betroffen",
                scenario="dictated_number",
                speaker_group="g2",
                audio_path=None,
                transcript="die zwölf ist betroffen",
                extra={},
            ),
        ]
        bench = await run_stt_benchmark(FakeSTT(""), "fake-model", samples)  # type: ignore[arg-type]
        summary = bench.summary()
        assert summary["wer_mean"] == 0.0
        assert summary["failures"] == 0

    async def test_bad_sample_recorded_as_failure_not_crash(self, tmp_path: Path) -> None:
        class Boom:
            async def transcribe(
                self, audio: bytes, *, audio_format: str = "wav", language: str = "de"
            ) -> tuple[str, dict[str, float]]:
                raise RuntimeError("kaboom")

        import soundfile as sf

        audio = tmp_path / "s1.wav"
        sf.write(audio, np.zeros(8000, dtype="float32"), 8000)
        samples = [
            Sample(
                id="s1",
                reference="x",
                scenario="general",
                speaker_group="g1",
                audio_path=audio,
                transcript=None,
                extra={},
            )
        ]
        bench = await run_stt_benchmark(Boom(), "boom-model", samples)  # type: ignore[arg-type]
        assert bench.results == [] and len(bench.failures) == 1


@pytest.fixture
async def knowledge_service(tmp_path: Path) -> KnowledgeService:
    doc = tmp_path / "faq.md"
    doc.write_text(
        "# Ordnungsamt\n\n"
        "Der Ordnungsamt Bürgerservice ist montags bis freitags "
        "von 9 bis 17 Uhr geöffnet.\n",
        encoding="utf-8",
    )
    source, text = source_from_file(
        doc,
        document_id="faq-1",
        tenant_id="demo",
        service="ordnungsamt",
        version="1",
        source_uri="s3://demo/ordnungsamt-faq.md",
        effective_from=datetime(2026, 1, 1),
        title="Ordnungsamt FAQ",
    )
    chunks = await prepare_chunks(source, text, HashEmbeddingProvider())
    repo = InMemoryKnowledgeRepository()
    await repo.publish(chunks)
    return KnowledgeService(repo, HashEmbeddingProvider())


class TestRetrievalEval:
    async def test_recall_and_mrr(self, knowledge_service: KnowledgeService) -> None:
        from datetime import datetime as dt

        from services.knowledge.models import RetrievalQuery

        first = await knowledge_service.search(
            RetrievalQuery(
                text="Wann ist das Ordnungsamt geöffnet?",
                tenant_id="demo",
                at=dt(2026, 6, 1),
                limit=3,
            )
        )
        assert first, "fixture document must be retrievable"
        metrics = await run_retrieval_eval(
            knowledge_service,
            [
                RetrievalCase(
                    query="Wann ist das Ordnungsamt geöffnet?",
                    relevant_source_ids={first[0].source_id},
                )
            ],
            k=3,
        )
        assert metrics["recall@3"] == 1.0
        assert metrics["mrr"] == 1.0


class SlotFillingRunner:
    """Deterministic slot-filling agent: extracts name/street/number by regex."""

    def run_turn(self, *, transcript: str, state: CallState, generation: int) -> AsyncIterator[str]:
        import re

        async def _stream() -> AsyncIterator[str]:
            if m := re.search(r"Name ist (\w+)", transcript):
                yield f"Vielen Dank, {m.group(1)}. Worum geht es?"
            elif "straße" in transcript.lower():
                yield "Danke, ich habe die Straße notiert."
            elif m := re.search(r"(\d+)", transcript):
                yield f"Die Hausnummer {m.group(1)} habe ich vermerkt."
            else:
                yield "Können Sie das bitte wiederholen?"

        return _stream()


class TestScenarios:
    async def test_full_intake_scenario_passes(self) -> None:
        machine = CallStateMachine(CallState(call_id="s", tenant_id="demo"))
        scenario = Scenario(
            id="intake",
            turns=[
                "Mein Name ist Müller",
                "Es geht um die Bergmannstraße",
                "Die Hausnummer ist 12",
            ],
            expect=Expectation(max_questions=10),
        )
        result = await run_scenario(scenario, machine, SlotFillingRunner())  # type: ignore[arg-type]
        assert result.passed, result.failures
        assert not result.questions_repeated

    async def test_repetition_detected(self) -> None:
        assert repetition_detected(["Wie lautet die Straße?", "Wie lautet die Straße?"])
        assert not repetition_detected(["Wie lautet die Straße?", "Und die Hausnummer?"])


class TestLoadHarness:
    async def test_admission_and_completion(self) -> None:
        report = await run_load(calls=20, turns_per_call=3, max_concurrent=8, think_ms=25)
        summary = report.summary()
        assert summary["admitted"] == 8
        assert summary["rejected"] == 12
        assert summary["completed_turns"] == 24
        assert summary["errors"] == 0

    async def test_all_admitted_when_capacity_allows(self) -> None:
        report = await run_load(calls=5, turns_per_call=2, max_concurrent=10)
        summary = report.summary()
        assert summary["admitted"] == 5 and summary["rejected"] == 0
        assert summary["completed_turns"] == 10
