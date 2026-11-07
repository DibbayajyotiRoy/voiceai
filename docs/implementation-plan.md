# Implementation plan

Each phase ends with runnable evidence. Hardware- and credential-dependent checks remain explicitly pending when unavailable.

## Phase 1 — Foundation

- [ ] Python 3.12/uv backend and Next.js/TypeScript/Tailwind presentation.
- [ ] Versioned audio, transcript, turn, tool, state, and telemetry contracts.
- [ ] Pinned dependencies and reproducible containers.
- [ ] Unit-test and lint/tooling setup.

## Phase 2 — Voice runtime

- [ ] Bounded Pipecat session lifecycle and FastAPI WebSocket replay.
- [ ] STT/TTS adapters and pydantic-ai bridge.
- [ ] VAD/turn detection, streaming clauses, barge-in, and generation cancellation.
- [ ] LiveKit WebRTC and SIP integration seams.

## Phase 3 — State, context, and knowledge

- [ ] Typed Pipecat Flows/`CallState` transitions and targeted corrections.
- [ ] Context compaction, progressive disclosure, and token accounting.
- [ ] Versioned ingestion, S3 originals, PostgreSQL/pgvector hybrid retrieval.
- [ ] Offline graph-assisted retrieval comparison.
- [ ] Tenant filters, unsupported-scope behavior, and handoff.

## Phase 4 — Providers

- [ ] OpenRouter multi-key registry, budgets, safe rotation, and routing.
- [ ] OpenRouter STT/TTS/LLM adapters with streamed error handling.
- [ ] Bedrock Converse streaming, tools, configured model/Region/profile, and IAM boundaries.
- [ ] Safe retries, cancellation, cost accounting, and real-provider smoke tests.

## Phase 5 — Speech models

- [ ] Whisper, Parakeet, and Canary STT benchmark manifests.
- [ ] Qwen3-TTS and CosyVoice TTS benchmark manifests.
- [ ] Telephony augmentation and municipal entity datasets.
- [ ] PyTorch/NeMo fine-tuning entry points and leakage-resistant splits.
- [ ] Serving comparisons before/after measured optimizations.

## Phase 6 — Evals

- [ ] STT, TTS, end-to-end, state/context, and retrieval scorers.
- [ ] Fast PR checks and fixed audio regressions.
- [ ] Release reports with raw JSON, confidence intervals, and failures.
- [ ] Failed-call replay promotion without contaminating the holdout.

## Phase 7 — Capacity and operations

- [ ] Real-media load harness and representative traffic profile.
- [ ] Ramp, overload, steady-state, soak, and worker/node-failure scenarios.
- [ ] OpenTelemetry/Logfire traces and Prometheus/Grafana metrics.
- [ ] Cost-per-successful-call and symptom-driven debugging runbooks.

## Phase 8 — Demos

- [ ] One-command complete local/private German municipal scenario.
- [ ] Static Vercel presentation using bundled hardcoded sanitized artifacts.
- [ ] Interactive architecture, synchronized replay, incident trace, and result labels.
- [ ] Vercel Analytics, Speed Insights, and validated engagement events.
- [ ] Desktop/mobile/accessibility and production-build verification.

## Assumptions

This is initially a single-developer portfolio project with per-change checks and a minimal operating budget. Existing AWS credits and model entitlements are used where configured. Numeric product SLOs live in the evaluation document. No production citizen data is used without appropriate governance.
