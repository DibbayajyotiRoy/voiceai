from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TraceContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    call_id: str
    turn_id: str | None = None
    generation: int = Field(default=0, ge=0)
    attempt_id: str | None = None
    provider_alias: str | None = None
    model_revision: str | None = None


class TelemetryEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=128)
    monotonic_ns: int = Field(ge=0)
    trace: TraceContext
    attributes: dict[str, str | int | float | bool] = Field(default_factory=dict)
