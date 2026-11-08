from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Protocol

from services.knowledge.embeddings import EmbeddingProvider
from services.knowledge.models import DocumentChunk, Evidence, RetrievalQuery


class KnowledgeRepository(Protocol):
    async def publish(self, chunks: list[DocumentChunk]) -> None: ...

    async def search(self, query: RetrievalQuery, embedding: list[float]) -> list[Evidence]: ...


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def reciprocal_rank_fusion(rankings: list[list[str]], *, k: int = 60) -> dict[str, float]:
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, item_id in enumerate(ranking, start=1):
            scores[item_id] += 1.0 / (k + rank)
    return scores


class InMemoryKnowledgeRepository:
    def __init__(self) -> None:
        self._chunks: dict[str, DocumentChunk] = {}

    async def publish(self, chunks: list[DocumentChunk]) -> None:
        for chunk in chunks:
            self._chunks[chunk.chunk_id] = chunk

    async def search(self, query: RetrievalQuery, embedding: list[float]) -> list[Evidence]:
        eligible = [
            chunk
            for chunk in self._chunks.values()
            if chunk.tenant_id == query.tenant_id
            and chunk.language == query.language
            and chunk.access_scope == query.access_scope
            and (query.service is None or chunk.service == query.service)
            and chunk.effective_from <= query.at
            and (chunk.effective_to is None or query.at < chunk.effective_to)
        ]
        terms = set(re.findall(r"[\wäöüß]+", query.text.lower(), flags=re.UNICODE))
        lexical_scores = {
            chunk.chunk_id: self._lexical_score(chunk.text, terms) for chunk in eligible
        }
        lexical = sorted(eligible, key=lambda chunk: lexical_scores[chunk.chunk_id], reverse=True)
        semantic = sorted(
            eligible, key=lambda chunk: cosine(chunk.embedding, embedding), reverse=True
        )
        scores = reciprocal_rank_fusion(
            [
                [chunk.chunk_id for chunk in lexical if lexical_scores[chunk.chunk_id] > 0],
                [chunk.chunk_id for chunk in semantic],
            ]
        )
        by_id = {chunk.chunk_id: chunk for chunk in eligible}
        selected = sorted(scores, key=lambda chunk_id: scores[chunk_id], reverse=True)[
            : query.limit
        ]
        return [
            Evidence(
                chunk_id=chunk_id,
                source_id=f"{by_id[chunk_id].document_id}:{by_id[chunk_id].heading_path}",
                text=by_id[chunk_id].text,
                score=scores[chunk_id],
                source_uri=by_id[chunk_id].source_uri,
                version=by_id[chunk_id].version,
            )
            for chunk_id in selected
        ]

    @staticmethod
    def _lexical_score(text: str, terms: set[str]) -> float:
        tokens = re.findall(r"[\wäöüß]+", text.lower(), flags=re.UNICODE)
        if not tokens or not terms:
            return 0.0
        return sum(tokens.count(term) for term in terms) / math.sqrt(len(tokens))


class KnowledgeService:
    def __init__(self, repository: KnowledgeRepository, embeddings: EmbeddingProvider) -> None:
        self.repository = repository
        self.embeddings = embeddings

    async def search(self, query: RetrievalQuery) -> list[Evidence]:
        embedding = (await self.embeddings.embed([query.text]))[0]
        return await self.repository.search(query, embedding)
