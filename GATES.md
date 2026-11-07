# Gates: Charly-style voice project

OWNS: **

Scope: complete voice system, reproducible evaluation/load tooling, and independent static hosted presentation

- [ ] G1: backend contracts, state, retrieval, providers, and orchestration tests pass
  CHECK: uv run pytest -q && python3 -c "print('BACKEND_VERIFICATION_PASSED')"
  EXPECT: BACKEND_VERIFICATION_PASSED
  EVIDENCE: pending

- [ ] G2: backend lint and static typing pass
  CHECK: uv run ruff check . && uv run pyright && python3 -c "print('BACKEND_QUALITY_PASSED')"
  EXPECT: BACKEND_QUALITY_PASSED
  EVIDENCE: pending

- [ ] G3: a complete local voice scenario with correction, retrieval, tool, barge-in, and failure replay passes
  CHECK: uv run python -m services.orchestrator.demo
  EXPECT: LOCAL_VOICE_DEMO_PASSED
  EVIDENCE: pending

- [ ] G4: the presentation production build and bundled-data safety checks pass
  CHECK: npm --prefix apps/web run build && node scripts/verify-presentation.mjs
  EXPECT: PRESENTATION_VERIFICATION_PASSED
  EVIDENCE: pending

- [ ] G5: deployed presentation interactions and analytics are validated without PII or privileged dependencies
  CHECK: node scripts/verify-deployed-presentation.mjs
  EXPECT: DEPLOYED_PRESENTATION_PASSED
  EVIDENCE: pending

- [ ] G6: named hardware verifies 1,000 real concurrent media calls with SLOs, 30% headroom, stable soak memory, and worker failure recovery
  CHECK: uv run python -m loadtest.run --config loadtest/configs/concurrent-1000.json
  EXPECT: CONCURRENT_1000_PASSED
  EVIDENCE: pending

- [ ] G7: entitled Bedrock and OpenRouter streamed responses and tool calls pass without duplicate side effects
  CHECK: uv run python -m evals.provider_smoke
  EXPECT: REAL_PROVIDER_SMOKE_PASSED
  EVIDENCE: pending

- [ ] G8: pinned speech baselines and fine-tuned candidates pass frozen holdout quality and serving gates
  CHECK: uv run python -m evals.speech_release
  EXPECT: SPEECH_RELEASE_PASSED
  EVIDENCE: pending
