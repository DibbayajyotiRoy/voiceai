from datetime import UTC, datetime

from services.knowledge.embeddings import HashEmbeddingProvider
from services.knowledge.models import DocumentChunk


def sample_chunks() -> list[DocumentChunk]:
    rows = [
        (
            "parking",
            "Wohnsitzparkausweis: Sie benötigen den Fahrzeugschein und einen Wohnsitznachweis.",
        ),
        ("waste", "Biomüll: Die Abfuhrtermine stehen im aktuellen Abfallkalender."),
    ]
    embedder = HashEmbeddingProvider()
    vectors = embedder.embed_sync([text for _, text in rows])
    return [
        DocumentChunk(
            chunk_id=f"{service}:2026-01:0",
            document_id=service,
            tenant_id="municipality-a",
            service=service,
            language="de",
            text=text,
            heading_path="Anforderungen",
            source_uri=f"https://example.invalid/{service}",
            version="2026-01",
            access_scope="public_municipal_support",
            effective_from=datetime(2026, 1, 1, tzinfo=UTC),
            effective_to=datetime(2027, 1, 1, tzinfo=UTC),
            embedding=vector,
        )
        for (service, text), vector in zip(rows, vectors, strict=True)
    ]
