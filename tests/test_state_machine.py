import pytest
from contracts.state import CallPhase, CallState, SlotStatus

from services.orchestrator.state_machine import CallStateMachine, StateTransitionError


@pytest.fixture
def machine() -> CallStateMachine:
    return CallStateMachine(
        CallState(call_id="call-1", tenant_id="tenant-1"),
        required_slots=frozenset({"address", "reference"}),
    )


async def test_required_slots_prevent_premature_confirmation(machine: CallStateMachine) -> None:
    state = await machine.discover(0, "ticket")
    with pytest.raises(StateTransitionError, match="required slots"):
        await machine.request_confirmation(state.state_version)


async def test_confirmed_slots_are_not_requested_again(machine: CallStateMachine) -> None:
    state = await machine.discover(0, "ticket")
    state = await machine.set_slot(
        state.state_version, "address", "Musterstraße 21", confirmed=True
    )
    assert machine.next_missing_slots() == ["reference"]
    state = await machine.set_slot(state.state_version, "reference", "A-123", confirmed=True)
    state = await machine.request_confirmation(state.state_version)
    assert state.phase is CallPhase.CONFIRMING
    assert state.slots["address"].status is SlotStatus.CONFIRMED


async def test_targeted_correction_does_not_reset_other_slots(machine: CallStateMachine) -> None:
    state = await machine.discover(0, "ticket")
    state = await machine.set_slot(
        state.state_version, "address", "Musterstraße 21", confirmed=True
    )
    state = await machine.set_slot(state.state_version, "reference", "A-123", confirmed=True)
    state = await machine.request_confirmation(state.state_version)
    state = await machine.correct_slot(state.state_version, "address", "Musterstraße 12")
    assert state.phase is CallPhase.COLLECTING
    assert state.slots["address"].value == "Musterstraße 12"
    assert state.slots["address"].status is SlotStatus.PROVISIONAL
    assert state.slots["reference"].value == "A-123"


async def test_stale_transition_is_rejected(machine: CallStateMachine) -> None:
    await machine.discover(0, "ticket")
    with pytest.raises(StateTransitionError, match="stale"):
        await machine.set_slot(0, "address", "stale")


async def test_completed_action_cannot_be_repeated(machine: CallStateMachine) -> None:
    state = await machine.discover(0, "ticket")
    state = await machine.set_slot(
        state.state_version, "address", "Musterstraße 21", confirmed=True
    )
    state = await machine.set_slot(state.state_version, "reference", "A-123", confirmed=True)
    state = await machine.request_confirmation(state.state_version)
    state = await machine.begin_action(state.state_version, "ticket:A-123")
    state = await machine.complete_action(state.state_version, "ticket:A-123")
    with pytest.raises(StateTransitionError, match="already completed"):
        await machine.begin_action(state.state_version, "ticket:A-123")


async def test_barge_in_invalidates_generation(machine: CallStateMachine) -> None:
    state = await machine.interrupt()
    assert state.generation == 1
