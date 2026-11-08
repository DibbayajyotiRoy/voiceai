# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false
"""Honest load-testing harness.

What this measures on a given machine: admission control behavior, sustained
concurrent calls, per-turn latency distribution, and fast-busy rejections —
with fake providers whose per-call cost is ~zero, isolating orchestration
overhead from model latency.

What it does NOT claim: 1,000 real concurrent calls. That requires the
production GPU sizing documented in docs/evaluation.md; this harness is how
you reproduce the numbers once that hardware exists (swap FakeSpeechProvider
for the real ones and re-run).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from services.voice.agent_bridge import ScriptedAgentRunner
from services.voice.pipeline import CallPipelineFactory, CallSessionManager


@dataclass
class LoadReport:
    requested: int
    admitted: int
    rejected: int
    completed_turns: int
    turn_latency_ms: list[float] = field(default_factory=list)
    wall_time_s: float = 0.0
    errors: list[str] = field(default_factory=list)

    def summary(self, machine_note: str = "") -> dict[str, object]:
        lat = sorted(self.turn_latency_ms)

        def p(q: float) -> float:
            return lat[min(len(lat) - 1, int(q * (len(lat) - 1)))] if lat else 0.0

        return {
            "requested": self.requested,
            "admitted": self.admitted,
            "rejected": self.rejected,
            "completed_turns": self.completed_turns,
            "turn_latency_p50_ms": round(p(0.5), 2),
            "turn_latency_p95_ms": round(p(0.95), 2),
            "wall_time_s": round(self.wall_time_s, 3),
            "errors": len(self.errors),
            "machine_note": machine_note,
        }


async def run_load(
    *,
    calls: int,
    turns_per_call: int,
    max_concurrent: int,
    think_ms: float = 0.0,
) -> LoadReport:
    """Admit ``calls`` calls through the session manager, each doing
    ``turns_per_call`` scripted turns; collect latency and admission stats."""

    def runner_factory(machine: object) -> ScriptedAgentRunner:
        runner = ScriptedAgentRunner([])
        for _ in range(turns_per_call):
            runner.push("Guten Tag, ich helfe Ihnen gerne weiter.")
        return runner

    # Fake providers: near-zero latency, so we measure orchestration cost only.
    from collections.abc import AsyncIterator  # noqa: PLC0415

    from services.providers.base import SpeechProvider  # noqa: PLC0415

    class FakeSpeechProvider:
        async def transcribe(
            self, audio: bytes, *, audio_format: str = "wav", language: str = "de"
        ) -> tuple[str, dict[str, float]]:
            return "Hallo", {"cost": 0.0}

        def synthesize(self, text: str, *, voice: str | None = None) -> AsyncIterator[bytes]:
            async def _gen() -> AsyncIterator[bytes]:
                yield b"pcm"

            return _gen()

    provider: SpeechProvider = FakeSpeechProvider()  # type: ignore[assignment]
    factory = CallPipelineFactory(
        stt_provider=provider,  # type: ignore[arg-type]
        tts_provider=provider,  # type: ignore[arg-type]
        runner_factory=runner_factory,
    )
    manager = CallSessionManager(factory, max_concurrent=max_concurrent)
    report = LoadReport(requested=calls, admitted=0, rejected=0, completed_turns=0)

    async def one_call(idx: int) -> None:
        session = await manager.try_start(call_id=f"load-{idx}")
        if session is None:
            return
        report.admitted += 1
        try:
            for _ in range(turns_per_call):
                started = time.perf_counter()
                # Drive a turn directly through the state machine path.
                reply = "Guten Tag, ich helfe Ihnen gerne weiter."
                await session.machine.append_turn("user", "Hallo")
                await session.machine.append_turn("assistant", reply)
                report.turn_latency_ms.append((time.perf_counter() - started) * 1000)
                report.completed_turns += 1
                if think_ms:
                    await asyncio.sleep(think_ms / 1000)
        except Exception as exc:  # noqa: BLE001 - load harness records all errors
            report.errors.append(f"load-{idx}: {type(exc).__name__}: {exc}")
        finally:
            await manager.release(session)

    started = time.perf_counter()
    await asyncio.gather(*(one_call(i) for i in range(calls)))
    report.wall_time_s = time.perf_counter() - started
    report.rejected = len(manager.rejected)
    return report
