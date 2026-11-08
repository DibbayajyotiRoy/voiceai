from contracts.state import CallState, ConversationTurn

from services.knowledge.models import Evidence
from services.orchestrator.context import ContextBuilder, ContextPolicy


def test_context_contains_state_and_bounded_evidence() -> None:
    state = CallState(
        call_id="call-1",
        tenant_id="tenant-1",
        intent="parking",
        summary="Older confirmed request",
        recent_turns=[ConversationTurn(number=1, role="user", text="Previous")],
    )
    evidence = [
        Evidence(
            chunk_id="chunk-1",
            source_id="doc-1:section",
            text="x" * 100,
            score=1,
            source_uri="https://example.invalid",
            version="v1",
        )
    ]
    context = ContextBuilder(ContextPolicy(max_evidence_chars=40)).build(
        state=state,
        current_text="Current",
        evidence=evidence,
        tool_names=["search_knowledge"],
    )
    assert context["call"]["phase"] == "discovery"  # type: ignore[index]
    assert len(context["evidence"][0]["text"]) == 40  # type: ignore[index]
    assert context["messages"][-1]["content"] == "Current"  # type: ignore[index]
    assert context["tools"] == ["search_knowledge"]
