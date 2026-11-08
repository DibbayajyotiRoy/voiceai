from datetime import UTC, datetime, timedelta

from services.knowledge.embeddings import HashEmbeddingProvider
from services.knowledge.models import RetrievalQuery
from services.knowledge.repository import InMemoryKnowledgeRepository, KnowledgeService
from tests.knowledge_fixtures import sample_chunks


async def test_hybrid_search_returns_relevant_source() -> None:
    service = KnowledgeService(InMemoryKnowledgeRepository(), HashEmbeddingProvider())
    chunks = sample_chunks()
    await service.repository.publish(chunks)
    result = await service.search(
        RetrievalQuery(
            text="Welche Dokumente brauche ich für den Wohnsitzparkausweis?",
            tenant_id="municipality-a",
            service="parking",
            at=datetime.now(UTC),
        )
    )
    assert result
    assert "Fahrzeugschein" in result[0].text
    assert result[0].version == "2026-01"


async def test_tenant_and_expiry_filters_are_enforced() -> None:
    repository = InMemoryKnowledgeRepository()
    service = KnowledgeService(repository, HashEmbeddingProvider())
    await repository.publish(sample_chunks())
    wrong_tenant = await service.search(
        RetrievalQuery(text="Fahrzeugschein", tenant_id="municipality-b", at=datetime.now(UTC))
    )
    expired = await service.search(
        RetrievalQuery(
            text="Fahrzeugschein",
            tenant_id="municipality-a",
            at=datetime.now(UTC) + timedelta(days=3650),
        )
    )
    assert wrong_tenant == []
    assert expired == []


async def test_service_filter_narrows_retrieval() -> None:
    repository = InMemoryKnowledgeRepository()
    service = KnowledgeService(repository, HashEmbeddingProvider())
    await repository.publish(sample_chunks())
    result = await service.search(
        RetrievalQuery(
            text="Was ist der Fahrzeugschein?",
            tenant_id="municipality-a",
            service="waste",
            at=datetime.now(UTC),
        )
    )
    assert all(item.chunk_id.startswith("waste") for item in result)
