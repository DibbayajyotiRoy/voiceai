# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportMissingTypeStubs=false, reportCallIssue=false, reportAttributeAccessIssue=false
"""Bridge between Pipecat frames and the typed call orchestration layer.

AgentBridge is a FrameProcessor that sits between STT and TTS:
- TranscriptionFrame -> record user turn, run the agent, stream reply text
- InterruptionFrame  -> cancel the in-flight reply, bump call generation

The bridge never calls providers itself. It delegates the turn to an
AgentRunner (protocol); the pydantic-ai implementation is the only place
tool calls are executed.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from contracts.state import CallState
from loguru import logger
from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    TextFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from services.orchestrator.state_machine import CallStateMachine


@runtime_checkable
class AgentRunner(Protocol):
    """Produces the assistant reply text for one user turn."""

    def run_turn(
        self,
        *,
        transcript: str,
        state: CallState,
        generation: int,
    ) -> AsyncIterator[str]: ...


class ScriptedAgentRunner:
    """Deterministic runner for tests and the local demo.

    Replies are popped in order per call. If the bridge is interrupted mid-turn
    (simulated barge-in), the runner notices the generation change and stops.
    """

    def __init__(self, replies: list[str] | None = None) -> None:
        self._replies = list(replies or [])
        self.requests: list[tuple[str, int]] = []

    def push(self, reply: str) -> None:
        self._replies.append(reply)

    def run_turn(
        self,
        *,
        transcript: str,
        state: CallState,
        generation: int,
    ) -> AsyncIterator[str]:
        self.requests.append((transcript, generation))
        reply = self._replies.pop(0) if self._replies else ""

        async def _stream() -> AsyncIterator[str]:
            # Yield word-by-word so interruption mid-stream is observable.
            for word in reply.split(" "):
                await asyncio.sleep(0)
                yield word + " "

        return _stream()


class AgentBridge(FrameProcessor):
    """Drives CallStateMachine and streams assistant text into the pipeline."""

    def __init__(self, machine: CallStateMachine, runner: AgentRunner) -> None:
        super().__init__()
        self._machine = machine
        self._runner = runner
        self._turn_task: asyncio.Task[None] | None = None

    @property
    def active_generation(self) -> int:
        return self._machine.snapshot.generation

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            await self._start_turn(frame.text)
        elif isinstance(frame, InterruptionFrame):
            await self._handle_interruption()

        # TranscriptionFrames are data frames and must keep flowing downstream.
        if direction is FrameDirection.DOWNSTREAM or isinstance(frame, TranscriptionFrame):
            await self.push_frame(frame, direction)

    async def _start_turn(self, transcript: str) -> None:
        await self._cancel_turn()
        state = self._machine.snapshot
        generation = state.generation
        await self._machine.append_turn("user", transcript)
        self._turn_task = self.create_task(
            self._stream_reply(transcript, generation), name="agent-turn"
        )

    async def _stream_reply(self, transcript: str, generation: int) -> None:
        try:
            reply_parts: list[str] = []
            async for delta in self._runner.run_turn(
                transcript=transcript,
                state=self._machine.snapshot,
                generation=generation,
            ):
                # Barge-in guard: never speak from a superseded generation.
                if self._machine.snapshot.generation != generation:
                    logger.info("Dropping stale reply from generation {}", generation)
                    return
                if delta:
                    reply_parts.append(delta)
                    await self.push_frame(TextFrame(delta))
            await self._machine.append_turn("assistant", "".join(reply_parts).strip())
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Agent turn failed")

    async def _handle_interruption(self) -> None:
        await self._cancel_turn()
        state = self._machine.snapshot
        await self._machine.interrupt()
        logger.debug("Barge-in: generation now {}", state.generation + 1)

    async def _cancel_turn(self) -> None:
        if self._turn_task is not None and not self._turn_task.done():
            await self.cancel_task(self._turn_task)
        self._turn_task = None
