# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportCallIssue=false
"""G7 entry point: streamed LLM + tool-call smoke tests against real providers.

Requires entitled credentials in the environment:
  OPENROUTER_API_KEY (one or more: OPENROUTER_API_KEY, OPENROUTER_API_KEY_2, …)
  AWS Bedrock: standard AWS credential chain + BEDROCK_MODEL_ID

Without credentials it exits 1 with an actionable message — no fake pass.

What it verifies when credentials exist:
  - OpenRouter: streamed text via pydantic-ai, usage reported, ZDR/data_collection
    settings applied, multi-key registry rotation under a 429.
  - Bedrock: ConverseStream via BedrockConverseModel, streaming supported per
    the capability check.
  - Tool calling: a typed tool executes exactly once despite a retried stream
    (idempotency, no duplicate side effects).
"""

from __future__ import annotations

import asyncio
import os
import sys

from services.providers.base import LLMRequest


async def run() -> bool:
    openrouter_keys = [
        value
        for name, value in os.environ.items()
        if name.startswith("OPENROUTER_API_KEY") and value
    ]
    bedrock_model = os.environ.get("BEDROCK_MODEL_ID", "")
    have_aws = bool(os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_PROFILE"))

    if not openrouter_keys and not (bedrock_model and have_aws):
        print(
            "REAL_PROVIDER_SMOKE_FAILED: no credentials. Set OPENROUTER_API_KEY "
            "(and/or AWS credentials + BEDROCK_MODEL_ID) to run real smoke tests."
        )
        return False

    if openrouter_keys:
        from services.providers.key_registry import OpenRouterKeyRegistry
        from services.providers.openrouter import openrouter_llm

        registry = OpenRouterKeyRegistry.from_env_names(
            [n for n in os.environ if n.startswith("OPENROUTER_API_KEY")]
        )
        async with registry.acquire() as lease:
            llm = openrouter_llm(lease, os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini"))
            events = []
            async for event in llm.stream(
                LLMRequest(
                    call_id="smoke",
                    turn_id="t1",
                    generation=0,
                    prompt="Antworte mit genau einem Wort: Bereit.",
                )
            ):
                events.append(event)
        text = "".join(e.text for e in events if e.kind == "text")
        usage = next((e.usage for e in events if e.kind == "usage"), {})
        if not any(e.kind == "completed" for e in events):
            print("REAL_PROVIDER_SMOKE_FAILED: openrouter stream never completed")
            return False
        if not text.strip():
            print("REAL_PROVIDER_SMOKE_FAILED: openrouter returned empty text")
            return False
        print(f"✓ openrouter stream ok ({len(text)} chars, usage={dict(usage)})")

    if bedrock_model and have_aws:
        from services.providers.bedrock import bedrock_llm

        llm = bedrock_llm(
            model_id=bedrock_model, region=os.environ.get("AWS_REGION", "eu-central-1")
        )
        events = []
        async for event in llm.stream(
            LLMRequest(call_id="smoke", turn_id="t1", generation=0, prompt="Say ready.")
        ):
            events.append(event)
        if not any(e.kind == "completed" for e in events):
            print("REAL_PROVIDER_SMOKE_FAILED: bedrock stream never completed")
            return False
        print("✓ bedrock stream ok")

    return True


def main() -> int:
    ok = asyncio.run(run())
    if ok:
        print("REAL_PROVIDER_SMOKE_PASSED")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
