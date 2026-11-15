# Gates: Charly-style voice project

OWNS: **

Scope: complete voice system, reproducible evaluation/load tooling, and independent static hosted presentation

- [x] G1: backend contracts, state, retrieval, providers, and orchestration tests pass
  CHECK: uv run pytest -q && python3 -c "print('BACKEND_VERIFICATION_PASSED')"
  EXPECT: BACKEND_VERIFICATION_PASSED
  EVIDENCE: met 2026-11-15 — 91 passed (tests/: media contracts, state machine, context, knowledge, providers, voice pipeline, WebRTC/Twilio transport, browser/dialed-call eval helpers, API/demo)

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
  EVIDENCE: MET 2026-11-08 for Bedrock: AWS_REGION=eu-central-1 BEDROCK_MODEL_ID=eu.anthropic.claude-haiku-4-5-20251001-v1:0 uv run python -m evals.provider_smoke → "✓ bedrock stream ok / REAL_PROVIDER_SMOKE_PASSED" (account verified by AWS; inference profile ID required). OpenRouter path still PENDING — no OPENROUTER_API_KEY in this environment. Mocked-transport tests remain green (tests/test_openrouter_speech.py, tests/test_key_registry.py).

- [ ] G8: pinned speech baselines and fine-tuned candidates pass frozen holdout quality and serving gates
  CHECK: uv run python -m evals.speech_release
  EXPECT: SPEECH_RELEASE_PASSED
  EVIDENCE: NOT MET — blocked on GPU box + [speech] extras + frozen holdout manifest. Entry point validates environment and data contract and exits 1 honestly otherwise. Model selection table and training plans exist (training/prepare.py, MODEL_RECIPES); all WER rows on the site are marked PENDING.

- [ ] G9: signed Twilio phone calls pass a handset smoke test and the same 25 turns used for WebRTC produce valid dialed-call audio and timing artifacts
  CHECK: uv run python evals/live/telephony_report.py evals/live/data/telephony-latency/client_latency.json evals/live/data/telephony-quality/client_latency.json --out evals/live/data/telephony-combined.json
  EXPECT: status completed with 25 requested turns and 25 valid turns; report measurement_scope twilio_dialed_e2e
  EVIDENCE: NOT MET — blocked on Twilio credentials and two voice-capable numbers. Signed webhook/admission tests and deterministic codec/timing/aggregation tests pass; no phone latency is claimed yet.
