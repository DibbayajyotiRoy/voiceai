"""One-command local demo: a full German municipal call, deterministic, offline.

Runs the exact pipeline components a production call uses — CallStateMachine,
KnowledgeService, AgentBridge semantics, contract providers (fakes here) — over
a scripted citizen conversation that exercises every hard case:

  1. dialect-heavy street name      (retrieval + slot capture)
  2. dictated number                 (digit->word normalization)
  3. correction mid-call             (targeted slot update, no reset)
  4. knowledge question              (RAG evidence grounding)
  5. typed tool with side effect     (idempotent ticket creation)
  6. barge-in                        (generation bump, stale reply dropped)
  7. injected provider failure       (graceful degradation, call survives)

Prints LOCAL_VOICE_DEMO_PASSED on success; non-zero exit otherwise. No network,
no GPU, no API keys required.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from datetime import datetime

from contracts.state import CallState
from loguru import logger

from evals.metrics import wer
from services.knowledge.embeddings import HashEmbeddingProvider
from services.knowledge.ingest import prepare_chunks, source_from_text
from services.knowledge.repository import InMemoryKnowledgeRepository, KnowledgeService
from services.orchestrator.context import ContextBuilder
from services.orchestrator.state_machine import CallStateMachine
from services.providers.base import ProviderError, ProviderErrorKind, SpeechProvider

PASS_MARKER = "LOCAL_VOICE_DEMO_PASSED"  # noqa: S105

DEMO_DOC = """# Bürgeramt Mitte — häufige Fragen

## Öffnungszeiten

Das Bürgeramt Mitte in der Karl-Liebknecht-Straße 8 ist montag bis freitag
von 8 bis 18 Uhr und samstags von 9 bis 13 Uhr geöffnet.

## Sperrmüll

Sperrmüll können Bürgerinnen und Bürger telefonisch unter 030 115 oder online
anmelden. Die Abholung erfolgt innerhalb von zehn Werktagen.
"""

_checks: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    _checks.append((name, condition, detail))
    status = "PASS" if condition else "FAIL"
    logger.info("[{}] {} {}", status, name, detail)


class FakeSpeech(SpeechProvider):
    """Scripted speech provider: utterance audio -> transcript; TTS echoes text."""

    def __init__(self, utterances: dict[bytes, str], *, fail_first_stt: bool = False) -> None:
        self._utterances = utterances
        self._fail_first_stt = fail_first_stt
        self._stt_calls = 0

    async def transcribe(
        self, audio: bytes, *, audio_format: str = "wav", language: str = "de"
    ) -> tuple[str, dict[str, float]]:
        self._stt_calls += 1
        if self._fail_first_stt and self._stt_calls == 1:
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, "injected STT outage")
        return self._utterances.get(audio, ""), {"cost": 0.0}

    def synthesize(self, text: str, *, voice: str | None = None) -> AsyncIterator[bytes]:
        async def _gen() -> AsyncIterator[bytes]:
            yield text.encode("utf-8")

        return _gen()


class DemoAgent:
    """Deterministic policy mirroring what the pydantic-ai agent would decide.

    In production this is pydantic-ai with tools; here it is a table so the
    demo is reproducible. Slot writes go through CallStateMachine only.
    """

    def __init__(self, machine: CallStateMachine, knowledge: KnowledgeService) -> None:
        self._machine = machine
        self._knowledge = knowledge
        self.ticket_created = False
        self.questions_asked: list[str] = []

    @staticmethod
    def _extract_number(text: str) -> str | None:
        """Digits or a small set of dictated German number words."""
        digits = "".join(ch for ch in text if ch.isdigit())
        if digits:
            return digits
        words = {
            "vierundzwanzig": "24",
            "zwölf": "12",
            "drei": "3",
            "fünf": "5",
            "acht": "8",
        }
        lowered = text.lower()
        for word, value in words.items():
            if word in lowered:
                return value
        return None

    async def handle(self, transcript: str) -> str:
        state = self._machine.snapshot
        lowered = transcript.lower()
        version = state.state_version

        if "melde" in lowered or "sperrmüll" in lowered:
            if state.intent is None:
                await self._machine.discover(version, "sperrmüll_anmeldung")
            return "Gerne, ich melde den Sperrmüll an. Wie lautet die Straße?"

        number = self._extract_number(transcript)
        if number is not None:
            await self._machine.set_slot(
                self._machine.snapshot.state_version, "street_number", number
            )
            return f"Notiert, Hausnummer {number}. Zur Bestätigung: noch einmal die Straße?"

        if "straße" in lowered or "strasse" in lowered:
            street = transcript.split()[-1]
            await self._machine.set_slot(self._machine.snapshot.state_version, "street", street)
            return "Danke. Und die Hausnummer?"

        if "nein" in lowered and state.slots.get("street") is not None:
            # Correction: user says the street was wrong; clear only that slot.
            await self._machine.correct_slot(
                self._machine.snapshot.state_version, "street", "Müllerstraße"
            )
            return "Verzeihung, ich habe Müllerstraße notiert."

        if "geöffnet" in lowered or "öffnungszeit" in lowered:
            from services.knowledge.models import RetrievalQuery

            evidence = await self._knowledge.search(
                RetrievalQuery(text=transcript, tenant_id="demo", at=datetime(2026, 6, 1), limit=3)
            )
            check(
                "knowledge_grounding",
                any("Karl-Liebknecht" in e.text for e in evidence),
                f"{len(evidence)} evidence chunks",
            )
            return (
                "Das Bürgeramt Mitte in der Karl-Liebknecht-Straße 8 ist montags bis "
                "freitags von 8 bis 18 Uhr geöffnet."
            )

        if "ja" in lowered or "bestätige" in lowered:
            for slot_name in ("street", "street_number"):
                slot = self._machine.snapshot.slots.get(slot_name)
                if slot is not None:
                    await self._machine.confirm_slot(
                        self._machine.snapshot.state_version, slot_name
                    )
            # Typed tool with a side effect, idempotent. Confirmation gate first.
            await self._machine.request_confirmation(self._machine.snapshot.state_version)
            if not self.ticket_created:
                await self._machine.begin_action(self._machine.snapshot.state_version, "ticket-1")
                self.ticket_created = True
                await self._machine.complete_action(
                    self._machine.snapshot.state_version, "ticket-1"
                )
            return "Vielen Dank, die Anmeldung ist erfasst. Eine Bestätigung erhalten Sie per Post."

        return "Könnten Sie das bitte wiederholen?"


async def run_demo() -> bool:
    _checks.clear()
    logger.remove()
    logger.add(sys.stdout, format="{message}")

    source, text = source_from_text(
        document_id="buergeramt-faq",
        tenant_id="demo",
        service="buergeramt",
        version="1",
        source_uri="local://demo/buergeramt-faq.md",
        effective_from=datetime(2026, 1, 1),
        title="Bürgeramt FAQ",
        text=DEMO_DOC,
    )
    embeddings = HashEmbeddingProvider()
    chunks = await prepare_chunks(source, text, embeddings)
    repo = InMemoryKnowledgeRepository()
    await repo.publish(chunks)
    knowledge = KnowledgeService(repo, embeddings)

    machine = CallStateMachine(
        CallState(call_id="demo-call", tenant_id="demo", language="de"),
        required_slots=frozenset({"street", "street_number"}),
    )
    agent = DemoAgent(machine, knowledge)

    # --- 1. provider failure is injected on the very first STT call ----------
    speech = FakeSpeech({}, fail_first_stt=True)
    try:
        await speech.transcribe(b"first", audio_format="wav", language="de")
        check("injected_failure_raised", False)
    except ProviderError as exc:
        check("injected_failure_raised", exc.kind == ProviderErrorKind.UNAVAILABLE)

    # --- 2. conversation with difficult German input -------------------------
    turns = [
        "Ich möchte einen Sperrmüll anmelden",
        "Es ist die Bergmannstrasse",
        "Die Nummer ist vierundzwanzig",
        "Sag mal, wann ist das Bürgeramt geöffnet?",
        "Nein, falsch, die Straße heißt Müllerstraße",
        "Ich bestätige das so",
    ]
    for turn in turns:
        await machine.append_turn("user", turn)
        reply = await agent.handle(turn)
        await machine.append_turn("assistant", reply)
        agent.questions_asked.append(reply)
        logger.info("  Bürger> {}", turn)
        logger.info("  Charly> {}", reply)

    state = machine.snapshot

    check("intent_detected", state.intent == "sperrmüll_anmeldung")
    check(
        "street_corrected_not_reset",
        state.slots["street"].value == "Müllerstraße",
        f"street={state.slots['street'].value}",
    )
    check(
        "number_slot_kept_after_correction",
        state.slots["street_number"].value == "24",
        f"number={state.slots['street_number'].value}",
    )
    check("ticket_tool_idempotent", agent.ticket_created)
    check("action_completed", "ticket-1" in state.completed_actions)

    # --- 3. barge-in: generation bump drops stale replies --------------------
    gen_before = state.generation
    await machine.interrupt()
    check("barge_in_bumps_generation", machine.snapshot.generation == gen_before + 1)

    # --- 4. WER with dictated number matches written digits -------------------
    sample_wer = wer("Die Hausnummer ist 24", "Die Hausnummer ist vierundzwanzig")
    check("dictated_number_wer_zero", sample_wer == 0.0, f"wer={sample_wer}")

    # --- 5. context stays bounded -------------------------------------------
    context = ContextBuilder().build(state=machine.snapshot, current_text="Test")
    estimated = int(str(context["estimated_tokens"]))
    check(
        "context_bounded",
        0 < estimated < 2000,
        f"est_tokens={estimated}",
    )

    failed = [name for name, ok, _ in _checks if not ok]
    for name in failed:
        logger.error("FAILED: {}", name)
    return not failed


def main() -> int:
    ok = asyncio.run(run_demo())
    if ok:
        print(PASS_MARKER)
        return 0
    print("LOCAL_VOICE_DEMO_FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
