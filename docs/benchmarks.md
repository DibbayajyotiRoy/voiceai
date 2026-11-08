# Benchmarks: how this system compares to other voice-AI stacks

This document compares the eval methodology and engineering posture of this
repository against commercial voice-agent platforms and model vendors. It
exists because "our agent sounds good" is not a benchmark — a reproducible
measurement pipeline is.

## Comparison axes

| Axis | This repo | Hosted platforms (Vapi, Retell, Bland, Synthflow) | Model APIs (OpenAI Realtime, Deepgram, AssemblyAI) |
|---|---|---|---|
| **Who owns the speech layer** | You — open STT/TTS fine-tuned on your domain, self-hosted on your GPUs | Vendor picks the models; you configure | Vendor's models only |
| **Eval reproducibility** | Every number has a command (`uv run pytest`, `loadtest`, `evals.*`); CI-gated releases | Vendor dashboards; you cannot re-run their WER on your audio | Published numbers on vendor-chosen corpora |
| **WER measured on** | Telephony-degraded audio (8 kHz, G.711 μ-law, seeded noise), German-normalized, digit-expansion aware | Typically not exposed per-customer | Vendor-internal test sets |
| **Data leakage control** | Speaker-group-split assignment by hash, asserted in tests (`check_no_leakage`) | Not applicable / not exposed | Not applicable / not exposed |
| **Latency measured as** | Per-turn waterfall: speech-end → endpoint → first token → first audio → playback | Voice-to-voice average (vendor-reported) | Component-level (TTFA etc., vendor-reported) |
| **Barge-in correctness** | Generation counters; stale-delta dropping is unit-tested | Supported, internals opaque | Supported, internals opaque |
| **Cost control** | Multi-key registry with per-key budgets, circuit breakers, local spend caps | Per-minute platform pricing | Per-token / per-minute API pricing |
| **EU data residency** | Self-hostable end-to-end; EU models, EU GPUs | Varies; usually US-region processing | Varies by vendor and region |
| **Debugging surface** | Per-call event flight recorder + Prometheus + runbook symptom→check table | Vendor logs and dashboards | Vendor logs |

## Vendor-published numbers (as advertised — not independently reproduced)

These figures come from vendor announcements and comparisons. They are useful
context, not measurements of this repo, and their methodologies differ from
ours (clean audio vs telephony-degraded, English-heavy vs German, streaming vs
batch).

| Vendor figure | Value | Source |
|---|---|---|
| Deepgram Nova-3 median streaming WER | 6.84% | [futureagi.com model roundup](https://futureagi.com/blog/best-voice-ai-april-2026/) |
| AssemblyAI Universal-2 WER claim | 14.5% | [futureagi.com model roundup](https://futureagi.com/blog/best-voice-ai-april-2026/) |
| Cartesia Sonic Turbo TTFA | ~40 ms | [futureagi.com model roundup](https://futureagi.com/blog/best-voice-ai-april-2026/) |
| ElevenLabs Flash v2.5 model inference | ~75 ms | [futureagi.com model roundup](https://futureagi.com/blog/best-voice-ai-april-2026/) |
| Retell voice-to-voice average | 780 ms (vs Synthflow 420 ms, same test script) | [retellai.com benchmark](https://www.retellai.com/resources/sub-second-latency-voice-assistants-benchmarks) |
| OpenAI Realtime (gpt-realtime) pricing | $32/$64 per M tokens | [futureagi.com model roundup](https://futureagi.com/blog/best-voice-ai-april-2026/) |

What these numbers have in common: none of them were measured on **your**
audio, **your** phone lines, or **your** accent distribution. That is the gap
this repo's `evals/` package closes — `evals.augment` degrades audio to real
PSTN conditions before WER is ever computed, and `evals.manifest` guarantees
the speakers in your eval set never appeared in training data.

## Where this repo stands today (measured, reproducible)

| Metric | Value | Command |
|---|---|---|
| Backend correctness | 54 tests passing | `uv run pytest -q` |
| Local voice scenario | 11/11 checks (correction, retrieval, tool, barge-in, failure) | `uv run python -m services.orchestrator.demo` |
| Admission control | 200 req / 50 admitted / 150 fast-busy / 0 errors; p50 turn 0.13 ms (orchestration only) | `loadtest.harness.run_load` |
| STT WER on telephony holdout | **PENDING** — frozen holdout eval runs on the GPU box | `uv run python -m evals.speech_release` |

The honest position: this repository does not yet publish WER or latency
numbers that beat the vendors above, because it refuses to publish numbers
that were not measured. The comparison it wins today is **methodology** —
leakage-safe, telephony-conditioned, CI-gated evaluation that most deployed
voice systems (commercial or DIY) do not have at all.
