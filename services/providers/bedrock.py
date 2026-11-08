# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportCallIssue=false
from __future__ import annotations

from typing import Any, cast

import boto3
from pydantic_ai.models.bedrock import BedrockConverseModel, BedrockModelName
from pydantic_ai.providers.bedrock import BedrockProvider

from services.providers.pydantic_provider import PydanticAIProvider


def bedrock_llm(
    *,
    model_id: str,
    region: str,
    alias: str = "bedrock-primary",
    client: Any | None = None,
) -> PydanticAIProvider:
    provider = BedrockProvider(region_name=region)
    if client is not None:
        provider = BedrockProvider(bedrock_client=client, region_name=region)
    model = BedrockConverseModel(cast(BedrockModelName, model_id), provider=provider)
    return PydanticAIProvider(alias=alias, model=model)


class BedrockCapabilityChecker:
    def __init__(self, *, region: str, client: Any | None = None) -> None:
        self.client = client or boto3.client("bedrock", region_name=region)

    def check_streaming(self, model_id: str) -> bool:
        response = self.client.get_foundation_model(modelIdentifier=model_id)
        return bool(response["modelDetails"]["responseStreamingSupported"])
