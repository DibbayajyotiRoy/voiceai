# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false
"""End-to-end conversation scenario eval.

A scenario is a scripted call: a list of user turns plus expectations on the
final call state (slots confirmed, no repeated questions, correct phase).
The agent side is any AgentRunner, so scenarios run against the deterministic
ScriptedAgentRunner in CI, or against a real LLM + tools for release gating.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from contracts.state import CallPhase

from evals.metrics import repetition_detected, slot_accuracy
from services.orchestrator.state_machine import CallStateMachine
from services.voice.agent_bridge import AgentRunner


@dataclass(frozen=True)
class Expectation:
    slots: dict[str, object] = field(default_factory=dict)
    phase: CallPhase | None = None
    max_questions: int = 12


@dataclass(frozen=True)
class Scenario:
    id: str
    turns: list[str]
    expect: Expectation


@dataclass
class ScenarioResult:
    scenario_id: str
    passed: bool
    slot_acc: float
    questions_repeated: bool
    question_count: int
    failures: list[str] = field(default_factory=list)


async def run_scenario(
    scenario: Scenario, machine: CallStateMachine, runner: AgentRunner
) -> ScenarioResult:
    """Play user turns through the runner; evaluate state afterwards.

    The runner is driven turn-by-turn with the evolving CallState, mirroring
    what AgentBridge does, without needing a live pipeline.
    """
    failures: list[str] = []
    asked: list[str] = []
    for turn in scenario.turns:
        state = machine.snapshot
        reply_parts: list[str] = []
        async for delta in runner.run_turn(
            transcript=turn, state=state, generation=state.generation
        ):
            reply_parts.append(delta)
        reply = "".join(reply_parts).strip()
        if reply:
            asked.append(reply)
            await machine.append_turn("user", turn)
            await machine.append_turn("assistant", reply)
        else:
            await machine.append_turn("user", turn)

    final = machine.snapshot
    slot_acc = slot_accuracy(scenario.expect.slots, dict(final.slots))
    repeated = repetition_detected(asked)
    if slot_acc < 1.0:
        failures.append(f"slot accuracy {slot_acc:.2f} < 1.0")
    if repeated:
        failures.append("agent repeated a question")
    if scenario.expect.phase is not None and final.phase is not scenario.expect.phase:
        failures.append(f"phase {final.phase} != expected {scenario.expect.phase}")
    if len(asked) > scenario.expect.max_questions:
        failures.append(f"{len(asked)} questions > max {scenario.expect.max_questions}")
    return ScenarioResult(
        scenario_id=scenario.id,
        passed=not failures,
        slot_acc=slot_acc,
        questions_repeated=repeated,
        question_count=len(asked),
        failures=failures,
    )
