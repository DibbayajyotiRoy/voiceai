from __future__ import annotations

import math
from typing import Protocol

from contracts.state import CallState, ConversationTurn


class EvidenceItem(Protocol):
    @property
    def source_id(self) -> str: ...

    @property
    def text(self) -> str: ...


class ContextPolicy:
    def __init__(
        self,
        *,
        max_recent_turns: int = 6,
        max_summary_chars: int = 1_600,
        max_evidence_chars: int = 2_400,
        max_evidence_items: int = 4,
    ) -> None:
        self.max_recent_turns = max_recent_turns
        self.max_summary_chars = max_summary_chars
        self.max_evidence_chars = max_evidence_chars
        self.max_evidence_items = max_evidence_items


class ContextBuilder:
    def __init__(self, policy: ContextPolicy | None = None) -> None:
        self.policy = policy or ContextPolicy()

    def build(
        self,
        *,
        state: CallState,
        current_text: str,
        evidence: list[EvidenceItem] | None = None,
        tool_names: list[str] | None = None,
    ) -> dict[str, object]:
        slots = {
            name: {"value": slot.value, "status": slot.status.value}
            for name, slot in sorted(state.slots.items())
        }
        selected_evidence = self._evidence(evidence or [])
        messages = [
            {"role": turn.role, "content": turn.text}
            for turn in state.recent_turns[-self.policy.max_recent_turns :]
        ]
        messages.append({"role": "user", "content": current_text})
        system = (
            "You are a concise German municipal voice assistant. Answer only from verified "
            "call state, supplied evidence, or authorized tools. Confirm sensitive values and "
            "actions. Clarify or request handoff when evidence is missing or outside scope."
        )
        return {
            "system": system,
            "call": {
                "tenant_id": state.tenant_id,
                "language": state.language,
                "phase": state.phase.value,
                "intent": state.intent,
                "slots": slots,
                "pending_action": state.pending_action,
            },
            "summary": state.summary[: self.policy.max_summary_chars],
            "evidence": selected_evidence,
            "tools": sorted(tool_names or []),
            "messages": messages,
            "estimated_tokens": self.estimate_tokens(
                system + state.summary + current_text + str(slots) + str(selected_evidence)
            ),
        }

    def _evidence(self, items: list[EvidenceItem]) -> list[dict[str, str]]:
        remaining = self.policy.max_evidence_chars
        result: list[dict[str, str]] = []
        for item in items[: self.policy.max_evidence_items]:
            if remaining <= 0:
                break
            text = item.text[:remaining]
            result.append({"source_id": item.source_id, "text": text})
            remaining -= len(text)
        return result

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return math.ceil(len(text) / 4)


class ConversationCompactor:
    def __init__(self, *, max_summary_chars: int = 1_600) -> None:
        self.max_summary_chars = max_summary_chars

    def compact(self, existing: str, evicted: list[ConversationTurn]) -> str:
        additions = [f"{turn.role}: {turn.text.strip()}" for turn in evicted if turn.text.strip()]
        combined = " | ".join(part for part in [existing, *additions] if part)
        if len(combined) <= self.max_summary_chars:
            return combined
        return combined[: self.max_summary_chars - 1].rsplit(" ", 1)[0] + "…"
