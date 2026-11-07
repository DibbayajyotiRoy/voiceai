# VoiceAI: municipal voice systems lab

A Charly-inspired engineering project for German municipal phone conversations. The repository contains two independent deliverables:

- **Full voice system:** Pipecat, FastAPI, pydantic-ai, open STT/TTS, OpenRouter, AWS Bedrock, PostgreSQL/pgvector, S3-compatible storage, evals, and load tooling.
- **Hosted presentation:** a static Vercel site with bundled demo content, recorded/replayed scenarios, architecture explanations, benchmark evidence, and privacy-conscious analytics.

## Status

Architecture and implementation documentation are approved. Code and measured results are added in the implementation phases. No benchmark, production-readiness, hiring, or 1,000-concurrent-call result is claimed before it is reproduced.

## Design summary

```text
WebRTC or SIP/RTP
       ↓
Pipecat real-time runtime
       ↓
Streaming STT → typed call state/context → pydantic-ai agent/tools → streaming TTS
                         │                         │
                PostgreSQL/pgvector          Bedrock/OpenRouter
                         │
                S3-compatible originals
```

The public presentation is separate and uses hardcoded sanitized data. It does not connect to S3, PostgreSQL, provider keys, or production systems.

## Documents

- [Architecture and decisions](docs/architecture.md)
- [Implementation plan](docs/implementation-plan.md)
- [Evaluation and capacity](docs/evaluation.md)
- [Presentation and analytics](docs/presentation.md)
- [Debugging runbook](docs/runbook.md)
- [Executable acceptance gates](GATES.md)

## Engineering targets

These are targets, not measured claims:

- p95 caller-end-to-first-audio below 1.5 seconds.
- p95 barge-in-to-silence below 250 ms.
- At least 99% successful completed test calls.
- No stale audio after cancellation.
- 1,000 simultaneous calls only after a named-hardware load test with 30% headroom.

## Privacy

Use synthetic or consented data. Keep credentials out of Git, logs, browser code, analytics properties, and demo artifacts. Apply tenant and authorization filters before retrieval. Public analytics cannot prove that a company or individual reviewer visited.
