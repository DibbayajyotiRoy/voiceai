from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path

from services.knowledge.embeddings import EmbeddingProvider
from services.knowledge.models import DocumentChunk, DocumentSource


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def chunk_text(text: str, *, max_chars: int = 1_200) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    heading = ""
    buffer: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        if block.startswith("#"):
            heading = block.lstrip("#").strip()
            if buffer:
                sections.append((heading, "\n\n".join(buffer)))
                buffer = []
            continue
        if sum(map(len, buffer)) + len(block) > max_chars and buffer:
            sections.append((heading, "\n\n".join(buffer)))
            buffer = []
        buffer.append(block)
    if buffer:
        sections.append((heading, "\n\n".join(buffer)))
    return sections


async def prepare_chunks(
    source: DocumentSource,
    text: str,
    embeddings: EmbeddingProvider,
) -> list[DocumentChunk]:
    sections = chunk_text(text)
    vectors = await embeddings.embed([body for _, body in sections])
    return [
        DocumentChunk(
            chunk_id=f"{source.document_id}:{source.version}:{index}",
            document_id=source.document_id,
            tenant_id=source.tenant_id,
            service=source.service,
            language=source.language,
            text=body,
            heading_path=heading,
            source_uri=source.source_uri,
            version=source.version,
            access_scope=source.access_scope,
            effective_from=source.effective_from,
            effective_to=source.effective_to,
            embedding=vector,
        )
        for index, ((heading, body), vector) in enumerate(zip(sections, vectors, strict=True))
    ]


def source_from_file(
    path: Path,
    *,
    document_id: str,
    tenant_id: str,
    service: str,
    version: str,
    source_uri: str,
    effective_from: datetime,
    title: str,
) -> tuple[DocumentSource, str]:
    data = path.read_bytes()
    source = DocumentSource(
        document_id=document_id,
        tenant_id=tenant_id,
        service=service,
        source_uri=source_uri,
        version=version,
        content_hash=content_hash(data),
        effective_from=effective_from,
        title=title,
    )
    return source, data.decode("utf-8")
