# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportMissingTypeStubs=false, reportCallIssue=false, reportAttributeAccessIssue=false
"""Per-call Pipecat pipeline assembly and bounded session lifecycle.

CallPipelineFactory wires the fixed pipeline shape:

    transport -> ContractSTTService -> AgentBridge -> ContractTTSService -> transport

CallSessionManager owns PipelineWorker lifecycle for many concurrent calls and
enforces a hard concurrency bound: sessions beyond the limit are rejected
immediately (fast busy) instead of queueing, which is what keeps tail latency
predictable under load.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable

from contracts.state import CallState
from loguru import logger
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker
from pipecat.workers.runner import WorkerRunner

from services.orchestrator.state_machine import CallStateMachine
from services.providers.base import SpeechProvider
from services.voice.adapters import ContractSTTService, ContractTTSService
from services.voice.agent_bridge import AgentBridge, AgentRunner
from services.voice.transport import InMemoryCallTransport


class CallPipelineFactory:
    """Builds one pipeline per call. All call-specific state is injected per call."""

    def __init__(
        self,
        *,
        stt_provider: SpeechProvider,
        tts_provider: SpeechProvider,
        runner_factory: Callable[[CallStateMachine], AgentRunner],
        required_slots: frozenset[str] = frozenset(),
    ) -> None:
        self._stt_provider = stt_provider
        self._tts_provider = tts_provider
        self._runner_factory = runner_factory
        self._required_slots = required_slots

    def build(
        self, *, call_id: str, tenant_id: str, language: str = "de"
    ) -> tuple[
        Pipeline,
        CallStateMachine,
        AgentBridge,
        InMemoryCallTransport,
        ContractSTTService,
        ContractTTSService,
    ]:
        transport = InMemoryCallTransport(call_id=call_id)
        machine = CallStateMachine(
            CallState(call_id=call_id, tenant_id=tenant_id, language=language),
            required_slots=self._required_slots,
        )
        bridge = AgentBridge(machine, self._runner_factory(machine))
        stt = ContractSTTService(self._stt_provider, language=language)
        tts = ContractTTSService(self._tts_provider)
        # Pipecat pipelines are linear; the transport is represented by the
        # caller injecting frames at the source and reading the bot audio sink.
        pipeline = Pipeline([stt, bridge, tts])
        return pipeline, machine, bridge, transport, stt, tts


class CallSession:
    """One running call: owns the PipelineWorker and its final state."""

    def __init__(
        self,
        *,
        session_id: str,
        worker: PipelineWorker,
        machine: CallStateMachine,
        transport: InMemoryCallTransport,
        stt: ContractSTTService,
        tts: ContractTTSService,
    ) -> None:
        self.session_id = session_id
        self.worker = worker
        self.machine = machine
        self.transport = transport
        self.stt = stt
        self.tts = tts

    async def cancel(self) -> None:
        await self.worker.cancel(reason="session cancelled")


class CallSessionManager:
    """Runs up to ``max_concurrent`` calls; rejects the rest with fast-busy.

    This is the first load-shedding line of defense for the 1,000-call claim:
    admission control happens before any provider token is spent.
    """

    def __init__(self, factory: CallPipelineFactory, *, max_concurrent: int = 100) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        self._factory = factory
        self._max_concurrent = max_concurrent
        self._slots = asyncio.Semaphore(max_concurrent)
        self._sessions: dict[str, CallSession] = {}
        self.rejected: list[str] = []

    @property
    def active(self) -> int:
        return len(self._sessions)

    @property
    def capacity(self) -> int:
        return self._max_concurrent

    async def try_start(
        self, *, call_id: str | None = None, tenant_id: str = "demo", language: str = "de"
    ) -> CallSession | None:
        """Start a call if capacity allows, else return None (fast busy)."""
        session_id = call_id or uuid.uuid4().hex[:12]
        # Non-blocking admission: no await between the check and acquire, so the
        # decision is atomic within the event loop. Beyond capacity -> fast busy.
        if self._slots._value <= 0:  # noqa: SLF001
            self.rejected.append(session_id)
            logger.info("Fast busy: at capacity ({})", self._max_concurrent)
            return None
        await self._slots.acquire()
        try:
            pipeline, machine, _bridge, transport, stt, tts = self._factory.build(
                call_id=session_id, tenant_id=tenant_id, language=language
            )
            worker = PipelineWorker(pipeline, cancel_on_idle_timeout=False)
            session = CallSession(
                session_id=session_id,
                worker=worker,
                machine=machine,
                transport=transport,
                stt=stt,
                tts=tts,
            )
            self._sessions[session_id] = session
            return session
        except Exception:
            self._slots.release()
            raise

    async def release(self, session: CallSession) -> None:
        self._sessions.pop(session.session_id, None)
        try:
            await session.worker.stop_when_done()
        except Exception:
            logger.debug("worker stop raised during release", exc_info=True)
        self._slots.release()

    async def run(self, session: CallSession) -> None:
        runner = WorkerRunner()
        await runner.add_workers(session.worker)
        await runner.run()

    async def shutdown(self) -> None:
        for session in list(self._sessions.values()):
            await session.cancel()
        self._sessions.clear()
