from __future__ import annotations

import asyncio
from collections.abc import Callable

from contracts.state import CallPhase, CallState, ConversationTurn, SlotStatus, SlotValue


class StateTransitionError(RuntimeError):
    pass


_ALLOWED_TRANSITIONS: dict[CallPhase, frozenset[CallPhase]] = {
    CallPhase.DISCOVERY: frozenset({CallPhase.COLLECTING, CallPhase.HANDOFF}),
    CallPhase.COLLECTING: frozenset({CallPhase.CONFIRMING, CallPhase.HANDOFF}),
    CallPhase.CONFIRMING: frozenset(
        {
            CallPhase.COLLECTING,
            CallPhase.EXECUTING,
            CallPhase.HANDOFF,
        }
    ),
    CallPhase.EXECUTING: frozenset({CallPhase.COMPLETED, CallPhase.HANDOFF}),
    CallPhase.COMPLETED: frozenset({CallPhase.COLLECTING, CallPhase.HANDOFF}),
    CallPhase.HANDOFF: frozenset(),
}


class CallStateMachine:
    def __init__(self, initial: CallState, required_slots: frozenset[str] = frozenset()) -> None:
        self._state = initial.model_copy(deep=True)
        self._required_slots = required_slots
        self._lock = asyncio.Lock()

    @property
    def snapshot(self) -> CallState:
        return self._state.model_copy(deep=True)

    async def _update(
        self,
        expected_version: int,
        mutation: Callable[[CallState], None],
        target: CallPhase | None = None,
    ) -> CallState:
        async with self._lock:
            if self._state.state_version != expected_version:
                raise StateTransitionError("stale state version")
            candidate = self._state.model_copy(deep=True)
            if target is not None and target is not candidate.phase:
                if target not in _ALLOWED_TRANSITIONS[candidate.phase]:
                    raise StateTransitionError(
                        f"transition {candidate.phase} -> {target} is not allowed"
                    )
                candidate.phase = target
            mutation(candidate)
            candidate.state_version += 1
            self._state = candidate
            return self.snapshot

    async def discover(self, version: int, intent: str) -> CallState:
        def mutate(state: CallState) -> None:
            state.intent = intent

        return await self._update(version, mutate, CallPhase.COLLECTING)

    async def set_slot(
        self, version: int, name: str, value: str, *, confirmed: bool = False
    ) -> CallState:
        if self.snapshot.phase not in {CallPhase.COLLECTING, CallPhase.CONFIRMING}:
            raise StateTransitionError("slots can be changed only while collecting or confirming")

        def mutate(state: CallState) -> None:
            state.slots[name] = SlotValue(
                value=value,
                status=SlotStatus.CONFIRMED if confirmed else SlotStatus.PROVISIONAL,
                source_turn=state.turn_count,
            )
            state.pending_action = None

        return await self._update(version, mutate)

    async def confirm_slot(self, version: int, name: str) -> CallState:
        slot = self.snapshot.slots.get(name)
        if slot is None or slot.status is SlotStatus.MISSING:
            raise StateTransitionError(f"cannot confirm missing slot {name}")

        def mutate(state: CallState) -> None:
            state.slots[name].status = SlotStatus.CONFIRMED

        return await self._update(version, mutate)

    async def request_confirmation(self, version: int) -> CallState:
        missing = self.next_missing_slots(self.snapshot)
        if missing:
            raise StateTransitionError(f"required slots are not confirmed: {', '.join(missing)}")
        return await self._update(version, lambda _: None, CallPhase.CONFIRMING)

    async def correct_slot(self, version: int, name: str, value: str) -> CallState:
        if self.snapshot.phase in {CallPhase.EXECUTING, CallPhase.COMPLETED}:
            raise StateTransitionError("an executed action requires a compensating workflow")

        async def mutate(state: CallState) -> None:
            state.slots[name] = SlotValue(
                value=value,
                status=SlotStatus.PROVISIONAL,
                source_turn=state.turn_count,
            )
            state.pending_action = None

        # Keep the update atomic while allowing a confirmation-phase correction.
        async with self._lock:
            if self._state.state_version != version:
                raise StateTransitionError("stale state version")
            candidate = self._state.model_copy(deep=True)
            if candidate.phase is CallPhase.CONFIRMING:
                candidate.phase = CallPhase.COLLECTING
            elif candidate.phase is not CallPhase.COLLECTING:
                raise StateTransitionError("correction is not valid in the current phase")
            await mutate(candidate)
            candidate.state_version += 1
            self._state = candidate
            return self.snapshot

    async def begin_action(self, version: int, action_id: str) -> CallState:
        if action_id in self.snapshot.completed_actions:
            raise StateTransitionError("action has already completed")

        def mutate(state: CallState) -> None:
            if state.pending_action is not None:
                raise StateTransitionError("another action is already pending")
            state.pending_action = action_id

        return await self._update(version, mutate, CallPhase.EXECUTING)

    async def complete_action(self, version: int, action_id: str) -> CallState:
        if self.snapshot.pending_action != action_id:
            raise StateTransitionError("completed action does not match the pending action")

        def mutate(state: CallState) -> None:
            state.completed_actions.add(action_id)
            state.pending_action = None

        return await self._update(version, mutate, CallPhase.COMPLETED)

    async def append_turn(self, role: str, text: str, *, max_recent: int = 8) -> CallState:
        async with self._lock:
            candidate = self._state.model_copy(deep=True)
            candidate.recent_turns.append(
                ConversationTurn(
                    number=candidate.turn_count,
                    role=role,
                    text=text,
                    generation=candidate.generation,
                )
            )
            candidate.turn_count += 1
            candidate.recent_turns = candidate.recent_turns[-max_recent:]
            candidate.state_version += 1
            self._state = candidate
            return self.snapshot

    async def interrupt(self) -> CallState:
        async with self._lock:
            candidate = self._state.model_copy(deep=True)
            candidate.generation += 1
            candidate.pending_action = (
                None if candidate.phase is not CallPhase.EXECUTING else candidate.pending_action
            )
            candidate.state_version += 1
            self._state = candidate
            return self.snapshot

    async def replace_summary(self, summary: str, *, expected_version: int) -> CallState:
        return await self._update(
            expected_version, lambda state: setattr(state, "summary", summary)
        )

    def next_missing_slots(self, state: CallState | None = None) -> list[str]:
        current = state or self._state
        return [
            name
            for name in sorted(self._required_slots)
            if current.slots.get(name, SlotValue()).status is not SlotStatus.CONFIRMED
        ]
