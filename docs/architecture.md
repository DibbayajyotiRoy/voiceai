# Architecture and decisions

## Purpose

The system answers German municipal questions and completes typed tools while handling noisy telephone audio, corrections, interruptions, and provider failures. The design favors measurable components over a single opaque speech model.

## Runtime path

1. WebRTC carries browser audio; SIP/RTP carries telephone audio. WebSocket supports the first deterministic local replay.
2. Pipecat owns media frames, voice activity, turns, interruption propagation, context aggregation, and paced playback.
3. Internal STT/TTS services use binary protobuf over gRPC. Audio is decoded to PCM without Base64.
4. A single-writer `CallState` stores the workflow phase, typed slots, pending actions, and generation IDs.
5. A context builder supplies stable instructions, current state, recent turns, compacted history, selected evidence, and allowed tools.
6. pydantic-ai owns model interaction and municipal tools. Bedrock Converse streaming and OpenRouter streaming remain HTTPS APIs.
7. Redacted call events are persisted asynchronously. Critical tool/idempotency records commit synchronously.

## Why these choices

| Choice | Reason | Boundary |
|---|---|---|
| Pipecat | Reuses real-time media and interruption machinery | It does not provide GPU capacity by itself |
| Cascaded STT/LLM/TTS | Each stage can be fine-tuned and evaluated | More components require explicit contracts and tracing |
| FastAPI control plane | Typed async APIs and WebSocket support | No GPU inference in the request event loop |
| Self-hosted speech first | EU control and open-model ownership | Hosted fallbacks require policy and latency checks |
| Bedrock + OpenRouter | Uses available credits and enables provider comparisons | Keys and credits do not create unlimited throughput |
| PostgreSQL + pgvector | Transactions, metadata, keyword search, and vectors together | Approximate search recall and filters need benchmarks |
| S3-compatible originals | Immutable/versioned large files without bloating the database | Demo mode does not use object storage |
| Hybrid RAG first | Simple and effective for direct questions | Graph retrieval must win an eval before adoption |
| Explicit workflow state | Prevents forgotten slots and repeated questions | Corrections use targeted repair transitions |

## Context strategy

The model receives the smallest useful context, not all company documents or the entire transcript. Older turns are compacted; confirmed slots remain structured. Tool results are reduced to useful outcomes and source references. Retrieval happens just in time.

Graphify-inspired indexing may map entities and relationships offline. The graph acts as an index, never as the full prompt. Responses must cite original source chunks; inferred graph edges are not evidence.

## Knowledge storage

Production-style deployment:

- Originals and graph artifacts: versioned EU S3-compatible storage.
- Metadata, chunks, embeddings, permissions, and validity dates: PostgreSQL/pgvector.
- Hot call state: owning worker memory with asynchronous checkpoints/events.
- Redis/Kafka: only after a measured distributed-state or event-fan-out requirement.

Public presentation:

- All knowledge, traces, scenarios, and result files are sanitized and bundled at build time.
- No S3, PostgreSQL, provider credentials, administrative mutations, or public inference endpoints.

## State example

```text
INTENT_DISCOVERY → COLLECT_DETAILS → CONFIRM → EXECUTE → COMPLETE
                         │
                         └─ targeted correction → CONFIRM corrected value
```

The next question comes from missing slots. Confirmed values are not requested again unless the caller corrects them. Late results from old generation IDs are discarded.

## Transport boundaries

- Browser: WebRTC/Opus; local replay may use WebSocket/PCM.
- Telephone: SIP signalling and RTP/PCMA or PCMU.
- Internal speech: streaming gRPC with binary PCM.
- Bedrock: AWS SDK event streams over HTTPS.
- OpenRouter: SSE over HTTPS.
- Persistence: asynchronous PostgreSQL writes outside the media hot path.
