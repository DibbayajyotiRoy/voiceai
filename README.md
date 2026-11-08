# VoiceAI: municipal voice systems lab

A Charly-inspired engineering project for German municipal phone conversations. The repository contains two independent deliverables:

- **Full voice system:** Pipecat, FastAPI, pydantic-ai, open STT/TTS, OpenRouter, AWS Bedrock, PostgreSQL/pgvector, S3-compatible storage, evals, and load tooling.
- **Hosted presentation:** a static Vercel site with bundled demo content, recorded/replayed scenarios, architecture explanations, benchmark evidence, and privacy-conscious analytics.

## Status

Implementation complete for the local/private system and the hosted presentation (2026-11-08). Gate status: **G1–G5 met, G6–G8 blocked** (see [GATES.md](GATES.md) for exact evidence and commands).

- 54 backend tests, strict Ruff + Pyright clean, deterministic German voice demo passing (`LOCAL_VOICE_DEMO_PASSED`).
- Admission control measured on this machine: 50 concurrent calls, 200 requested, 150 fast-busy rejections, 0 errors (orchestration-only, fake providers — not a 1,000-call claim).
- Live demo-mode site: https://voiceai-presentation.vercel.app (G4 + G5 verified against the deployment).
- Not claimed: 1,000 concurrent media calls (needs the production GPU fleet), live OpenRouter/Bedrock smoke (needs credentials), speech WER/MOS numbers (needs the GPU-box holdout eval). All three have runnable entry points that fail honestly until unblocked.

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
