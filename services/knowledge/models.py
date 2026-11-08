from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentSource(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: str
    tenant_id: str
    service: str
    language: str = "de"
    source_uri: str
    version: str
    content_hash: str = Field(min_length=64, max_length=64)
    access_scope: str = "public_municipal_support"
    effective_from: datetime
    effective_to: datetime | None = None
    title: str


class DocumentChunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: str
    document_id: str
    tenant_id: str
    service: str
    language: str
    text: str = Field(min_length=1)
    heading_path: str = ""
    source_uri: str
    version: str
    access_scope: str
    effective_from: datetime
    effective_to: datetime | None = None
    embedding: list[float] = Field(min_length=1)


class RetrievalQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str = Field(min_length=1)
    tenant_id: str
    service: str | None = None
    language: str = "de"
    access_scope: str = "public_municipal_support"
    at: datetime
    limit: int = Field(default=4, ge=1, le=20)


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: str
    source_id: str
    text: str
    score: float
    source_uri: str
    version: str
