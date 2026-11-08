from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from services.knowledge.models import DocumentChunk


class GraphNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str
    label: str
    source_chunk_ids: tuple[str, ...] = ()


class GraphEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    target: str
    relation: str
    confidence: str = "EXTRACTED"


class KnowledgeGraph:
    """Offline source-linked index; it never creates factual evidence by itself."""

    def __init__(self) -> None:
        self.nodes: dict[str, GraphNode] = {}
        self.edges: list[GraphEdge] = []

    @classmethod
    def from_chunks(cls, chunks: list[DocumentChunk]) -> KnowledgeGraph:
        graph = cls()
        service_chunks: dict[str, list[str]] = {}
        for chunk in chunks:
            service_id = f"service:{chunk.tenant_id}:{chunk.service}"
            service_chunks.setdefault(chunk.service, []).append(chunk.chunk_id)
            graph.nodes[chunk.chunk_id] = GraphNode(
                node_id=chunk.chunk_id,
                label=chunk.heading_path or chunk.document_id,
                source_chunk_ids=(chunk.chunk_id,),
            )
            graph.nodes[service_id] = GraphNode(node_id=service_id, label=chunk.service)
            graph.edges.append(
                GraphEdge(source=service_id, target=chunk.chunk_id, relation="documented_by")
            )
        return graph

    def related_chunks(self, service: str, tenant_id: str) -> list[str]:
        service_id = f"service:{tenant_id}:{service}"
        return [
            edge.target
            for edge in self.edges
            if edge.source == service_id and edge.confidence == "EXTRACTED"
        ]
