from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CallPhase(StrEnum):
    DISCOVERY = "discovery"
    COLLECTING = "collecting"
    CONFIRMING = "confirming"
    EXECUTING = "executing"
    COMPLETED = "completed"
    HANDOFF = "handoff"


class SlotStatus(StrEnum):
    MISSING = "missing"
    PROVISIONAL = "provisional"
    CONFIRMED = "confirmed"


class SlotValue(BaseModel):
    value: Any = None
    status: SlotStatus = SlotStatus.MISSING
    source_turn: int | None = Field(default=None, ge=0)


class ConversationTurn(BaseModel):
    model_config = ConfigDict(frozen=True)

    number: int = Field(ge=0)
    role: str
    text: str
    generation: int = Field(default=0, ge=0)


class CallState(BaseModel):
    call_id: str = Field(min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=128)
    language: str = "de"
    phase: CallPhase = CallPhase.DISCOVERY
    intent: str | None = None
    slots: dict[str, SlotValue] = Field(default_factory=dict)
    pending_action: str | None = None
    completed_actions: set[str] = Field(default_factory=set)
    state_version: int = Field(default=0, ge=0)
    generation: int = Field(default=0, ge=0)
    turn_count: int = Field(default=0, ge=0)
    recent_turns: list[ConversationTurn] = Field(default_factory=list[ConversationTurn])
    summary: str = ""


class StateTransition(BaseModel):
    model_config = ConfigDict(frozen=True)

    from_version: int = Field(ge=0)
    expected_phase: CallPhase
    event: str = Field(min_length=1)
