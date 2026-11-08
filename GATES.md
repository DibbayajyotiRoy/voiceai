# Gates: Charly-style voice project

OWNS: **

Scope: complete voice system, reproducible evaluation/load tooling, and independent static hosted presentation

- [x] G1: backend contracts, state, retrieval, providers, and orchestration tests pass
  CHECK: uv run pytest -q && python3 -c "print('BACKEND_VERIFICATION_PASSED')"
  EXPECT: BACKEND_VERIFICATION_PASSED
  EVIDENCE: met 2026-11-08 — 54 passed (tests/: media contracts, state machine, context, knowledge, providers, voice pipeline, evals, API/demo)

- [x] G2: backend lint and static typing pass
  CHECK: uv run ruff check . && uv run pyright && python3 -c "print('BACKEND_QUALITY_PASSED')"
  EXPECT: BACKEND_QUALITY_PASSED
  EVIDENCE: met 2026-11-08 — ruff "All checks passed!", pyright 0 errors (strict; untyped third-party internals carry per-file suppressions)

- [x] G3: a complete local voice scenario with correction, retrieval, tool, barge-in, and failure replay passes
  CHECK: uv run python -m services.orchestrator.demo
  EXPECT: LOCAL_VOICE_DEMO_PASSED
  EVIDENCE: met 2026-11-08 — 11/11 checks PASS (intent, street correction without reset, dictated number, RAG grounding, idempotent ticket, barge-in generation, WER 0.0, bounded context, injected STT failure)

- [x] G4: the presentation production build and bundled-data safety checks pass
  CHECK: npm --prefix apps/web run build && node scripts/verify-presentation.mjs
  EXPECT: PRESENTATION_VERIFICATION_PASSED
  EVIDENCE: met 2026-11-08 — static prerender, 15/15 checks (no S3/Postgres/key shapes/secret env names in bundle; 6 analytics events wired; MEASURED/PENDING markers present)

- [x] G5: deployed presentation interactions and analytics are validated without PII or privileged dependencies
  CHECK: node scripts/verify-deployed-presentation.mjs
  EXPECT: DEPLOYED_PRESENTATION_PASSED
  EVIDENCE: met 2026-11-08 against https://voiceai-presentation.vercel.app — 13/13 checks (sections rendered, honesty markers, no forms/PII inputs, no third-party trackers, Vercel instrumentation served). Note: analytics prove a visit happened, never who visited.

- [ ] G6: named hardware verifies 1,000 real concurrent media calls with SLOs, 30% headroom, stable soak memory, and worker failure recovery
  CHECK: uv run python -m loadtest.run --config loadtest/configs/concurrent-1000.json
  EXPECT: CONCURRENT_1000_PASSED
  EVIDENCE: NOT MET — blocked on production GPU fleet. The harness refuses to pass without media=true + named hardware in config (verified: exits 1 with explanation on this 8 GB laptop). What is measured: admission control at 50 concurrent calls (200 requested, 50 admitted, 150 fast-busy, 0 errors, p50 turn 0.13 ms orchestration overhead, fake providers).

- [ ] G7: entitled Bedrock and OpenRouter streamed responses and tool calls pass without duplicate side effects
  CHECK: uv run python -m evals.provider_smoke
  EXPECT: REAL_PROVIDER_SMOKE_PASSED
  EVIDENCE: NOT MET — blocked on credentials. Verified behavior without keys: exits 1 with actionable message. Code paths are covered by recorded-HTTP tests (tests/test_openrouter_speech.py, tests/test_key_registry.py) against mocked transports.

- [ ] G8: pinned speech baselines and fine-tuned candidates pass frozen holdout quality and serving gates
  CHECK: uv run python -m evals.speech_release
  EXPECT: SPEECH_RELEASE_PASSED
  EVIDENCE: NOT MET — blocked on GPU box + [speech] extras + frozen holdout manifest. Entry point validates environment and data contract and exits 1 honestly otherwise. Model selection table and training plans exist (training/prepare.py, MODEL_RECIPES); all WER rows on the site are marked PENDING.
