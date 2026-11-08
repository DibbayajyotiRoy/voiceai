# Evaluation and capacity

## Evidence rules

Every reported result must identify the code/model/dataset versions, hardware, runtime, audio conditions, warmup, concurrency, raw failures, and confidence intervals. Vendor numbers can shortlist a model but cannot qualify it for this workload. Targets and measured results are displayed separately.

## Metrics

| Layer | Required measurements |
|---|---|
| STT | Raw/normalized WER, entity/slot F1, exact numbers/dates, name/street recall, hallucination rate, partial stability, finalization delay, RTF/RTFx, memory, p50/p95/p99 |
| TTS | First audio, generation RTF, underruns, pronunciation/entity accuracy, telephone-codec intelligibility, calibrated human naturalness |
| Conversation | Task success, exact tools/arguments, corrections, false cutoff, false barge-in, interruption-to-silence, first audio, handoff |
| State/context | No repeated confirmed questions, valid transitions, correction rollback, compaction/interruption retention, tokens per successful call |
| Retrieval | Source correctness, tenant isolation, hybrid/graph recall, token use, latency, indexing cost |
| Cost | GPU, speech, LLM, providers, telephony, observability, retries, and failed calls per successful call/minute |

## Release gates

- Fast mocked contract/unit tests on each change.
- Fixed audio regression set for speech changes.
- Full GPU benchmark for nightly/release candidates.
- No statistically meaningful quality regression and no p95 latency regression above 10% without a reviewed trade-off.
- Failed calls become redacted replay fixtures; representative examples enter training only after regression promotion while preserving an untouched holdout.

## Capacity plan

The target is 1,000 simultaneously active calls, not 1,000 calls per day.

1. Measure real speaking duty cycles, turn lengths, token distributions, tools, languages, and call durations.
2. Measure stage RTF and latency under realistic concurrency; do not infer live capacity from offline throughput.
3. Ramp 100 → 500 → 1,000 active real-media sessions.
4. Run 60-minute steady state, 1,200-call overload, and multi-hour soak scenarios.
5. Repeat target load while terminating one worker/node.
6. Require 30% measured headroom, bounded queues, safe admission rejection, and no stale audio.
7. If named hardware cannot run the target, publish the largest verified result and remaining test. Never extrapolate a success claim.

## Initial product targets

- p95 caller-end-to-first-audio: < 1.5 s.
- p95 barge-in-to-silence: < 250 ms.
- Successful completed test calls: ≥ 99%.
- Stale audio after cancellation: 0.

## Current result ledger

Measured on this machine (2026-11-08), reproducible via the printed commands:

| Result | Value | Label | Command |
|---|---|---|---|
| Backend tests | 54 passed, 0 failed | measured | `uv run pytest -q` |
| Lint / strict typing | 0 ruff errors, 0 pyright errors | measured | `uv run ruff check . && uv run pyright` |
| Local voice scenario | 11/11 checks PASS | measured | `uv run python -m services.orchestrator.demo` |
| Admission control | 200 requested / 50 admitted / 150 fast-busy / 0 errors; p50 turn 0.13 ms (orchestration only, fake providers) | measured | `loadtest.harness.run_load` |
| Retrieval eval fixture | recall@3 = 1.0, MRR = 1.0 on 1-case fixture | measured (fixture only, not a quality claim) | `tests/test_evals.py` |

Pending (blocked, honestly labeled everywhere):

| Result | Blocker | Path |
|---|---|---|
| 1,000 concurrent media calls | production GPU fleet; harness refuses non-media configs | `loadtest/run.py` + `configs/concurrent-1000.json` |
| OpenRouter/Bedrock live smoke | entitled credentials | `evals/provider_smoke.py` |
| STT/TTS telephony WER + serving | GPU box, [speech] extras, frozen holdout | `evals/speech_release.py`, `training/prepare.py` |

Generated reports will be stored as versioned artifacts with a clear `measured`, `simulated`, or `target` label.
