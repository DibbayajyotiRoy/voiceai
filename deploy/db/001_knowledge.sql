CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    document_id text NOT NULL,
    version text NOT NULL,
    tenant_id text NOT NULL,
    source_uri text NOT NULL,
    published boolean NOT NULL DEFAULT FALSE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id, version)
);

CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id text PRIMARY KEY,
    document_id text NOT NULL,
    document_version text NOT NULL,
    tenant_id text NOT NULL,
    service text NOT NULL,
    language text NOT NULL,
    text text NOT NULL,
    heading_path text NOT NULL,
    source_uri text NOT NULL,
    access_scope text NOT NULL,
    effective_from timestamptz NOT NULL,
    effective_to timestamptz,
    embedding vector(256) NOT NULL,
    search_vector tsvector NOT NULL,
    FOREIGN KEY (document_id, document_version)
        REFERENCES documents(document_id, version) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS document_chunks_scope_idx
    ON document_chunks (tenant_id, service, language, access_scope);
CREATE INDEX IF NOT EXISTS document_chunks_keyword_idx
    ON document_chunks USING gin(search_vector);
CREATE INDEX IF NOT EXISTS document_chunks_embedding_idx
    ON document_chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS call_events (
    id bigserial PRIMARY KEY,
    call_id text NOT NULL,
    turn_id text,
    generation integer NOT NULL,
    event_name text NOT NULL,
    monotonic_ns bigint NOT NULL,
    attributes jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS call_events_call_idx ON call_events (call_id, id);

CREATE TABLE IF NOT EXISTS tool_idempotency (
    tenant_id text NOT NULL,
    idempotency_key text NOT NULL,
    request_hash text NOT NULL,
    status text NOT NULL,
    response jsonb,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, idempotency_key)
);
