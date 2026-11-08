# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false
from __future__ import annotations

from typing import Any

import asyncpg
from pgvector.asyncpg import register_vector

from services.knowledge.models import DocumentChunk, Evidence, RetrievalQuery
from services.knowledge.repository import reciprocal_rank_fusion


class PostgresKnowledgeRepository:
    def __init__(self, pool: Any) -> None:
        self.pool = pool

    @classmethod
    async def connect(cls, database_url: str) -> PostgresKnowledgeRepository:
        async def initialize(connection: Any) -> None:
            await register_vector(connection)

        pool = await asyncpg.create_pool(database_url, init=initialize)
        return cls(pool)

    async def close(self) -> None:
        await self.pool.close()

    async def publish(self, chunks: list[DocumentChunk]) -> None:
        async with self.pool.acquire() as connection:
            async with connection.transaction():
                for chunk in chunks:
                    await connection.execute(
                        """
                        INSERT INTO documents (
                            document_id, tenant_id, source_uri, version, published
                        ) VALUES ($1, $2, $3, $4, TRUE)
                        ON CONFLICT (document_id, version) DO UPDATE SET
                            source_uri = EXCLUDED.source_uri, published = TRUE
                        """,
                        chunk.document_id,
                        chunk.tenant_id,
                        chunk.source_uri,
                        chunk.version,
                    )
                    await connection.execute(
                        """
                        INSERT INTO document_chunks (
                            chunk_id, document_id, document_version, tenant_id, service,
                            language, text, heading_path, source_uri, access_scope,
                            effective_from, effective_to, embedding, search_vector
                        ) VALUES (
                            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                            to_tsvector('german', $7)
                        )
                        ON CONFLICT (chunk_id) DO UPDATE SET
                            text = EXCLUDED.text, embedding = EXCLUDED.embedding,
                            search_vector = EXCLUDED.search_vector,
                            effective_from = EXCLUDED.effective_from,
                            effective_to = EXCLUDED.effective_to
                        """,
                        chunk.chunk_id,
                        chunk.document_id,
                        chunk.version,
                        chunk.tenant_id,
                        chunk.service,
                        chunk.language,
                        chunk.text,
                        chunk.heading_path,
                        chunk.source_uri,
                        chunk.version,
                        chunk.access_scope,
                        chunk.effective_from,
                        chunk.effective_to,
                        chunk.embedding,
                    )

    async def search(self, query: RetrievalQuery, embedding: list[float]) -> list[Evidence]:
        async with self.pool.acquire() as connection:
            lexical = await connection.fetch(
                self._query("lexical"), *self._params(query, embedding)
            )
            semantic = await connection.fetch(
                self._query("semantic"), *self._params(query, embedding)
            )
            scores = reciprocal_rank_fusion(
                [[row["chunk_id"] for row in lexical], [row["chunk_id"] for row in semantic]]
            )
            selected = sorted(scores, key=lambda key: scores[key], reverse=True)[: query.limit]
            if not selected:
                return []
            rows = await connection.fetch(
                """
                SELECT chunk_id, document_id, text, heading_path, source_uri, document_version
                FROM document_chunks WHERE chunk_id = ANY($1)
                """,
                selected,
            )
        by_id = {row["chunk_id"]: row for row in rows}
        return [
            Evidence(
                chunk_id=chunk_id,
                source_id=f"{by_id[chunk_id]['document_id']}:{by_id[chunk_id]['heading_path']}",
                text=by_id[chunk_id]["text"],
                score=scores[chunk_id],
                source_uri=by_id[chunk_id]["source_uri"],
                version=by_id[chunk_id]["document_version"],
            )
            for chunk_id in selected
        ]

    @staticmethod
    def _params(query: RetrievalQuery, embedding: list[float]) -> tuple[object, ...]:
        return (
            query.tenant_id,
            query.language,
            query.access_scope,
            query.at,
            query.text,
            embedding,
            query.service,
        )

    @staticmethod
    def _query(kind: str) -> str:
        order = (
            "ts_rank_cd(search_vector, plainto_tsquery('german', $5)) DESC"
            if kind == "lexical"
            else "embedding <=> $6 ASC"
        )
        lexical_condition = (
            "AND search_vector @@ plainto_tsquery('german', $5)" if kind == "lexical" else ""
        )
        return f"""
            SELECT document_chunks.chunk_id FROM document_chunks
            JOIN documents ON
                documents.document_id = document_chunks.document_id
                AND documents.version = document_chunks.document_version
            WHERE document_chunks.tenant_id = $1
                AND document_chunks.language = $2
                AND document_chunks.access_scope = $3
                AND effective_from <= $4
                AND (effective_to IS NULL OR $4 < effective_to)
                AND ($7::text IS NULL OR service = $7)
                AND documents.published = TRUE
                {lexical_condition}
            ORDER BY {order} LIMIT 40
        """  # noqa: S608
