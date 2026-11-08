/**
 * Presentation data. Hardcoded, sanitized, presentation-only.
 *
 * Every number here is either (a) measured on this machine by the repo's own
 * tooling and reproducible via the printed command, or (b) explicitly marked
 * status: "pending" with the reason. Nothing is invented.
 *
 * Demo-mode rule: no S3, no PostgreSQL, no provider keys, no live inference.
 */

export type MeasuredStatus = "measured" | "pending";

export interface Metric {
  label: string;
  value: string;
  status: MeasuredStatus;
  command?: string;
  note?: string;
}

export const headlineMetrics: Metric[] = [
  {
    label: "Backend tests passing",
    value: "58",
    status: "measured",
    command: "uv run pytest -q",
  },
  {
    label: "Lint + type errors",
    value: "0",
    status: "measured",
    command: "uv run ruff check . && uv run pyright",
  },
  {
    label: "Full local scenario",
    value: "PASSED",
    status: "measured",
    command: "uv run python -m services.orchestrator.demo",
    note: "correction, retrieval, tool, barge-in, injected failure",
  },
  {
    label: "Turn overhead p50 (orchestration only)",
    value: "0.13 ms",
    status: "measured",
    command:
      "uv run python -c \"import asyncio; from loadtest.harness import run_load; ...\"",
    note: "50 concurrent calls, fake providers. Not a 1,000-call claim.",
  },
  {
    label: "1,000 concurrent media calls",
    value: "PENDING",
    status: "pending",
    note: "requires the production GPU fleet; harness ready: loadtest/run.py",
  },
  {
    label: "Fine-tuned STT WER vs baseline",
    value: "PENDING",
    status: "pending",
    note: "evals/speech_release.py. Frozen holdout, runs on the GPU box.",
  },
];

export interface SpeechModelRow {
  model: string;
  family: string;
  params: string;
  german: "strong" | "good" | "limited";
  license: string;
  serving: string;
  werTelephony: string;
  status: MeasuredStatus;
}

export const speechModels: SpeechModelRow[] = [
  {
    model: "nvidia/parakeet-tdt-0.6b-v3",
    family: "Parakeet (Canary)",
    params: "0.6B",
    german: "strong",
    license: "CC-BY-4.0",
    serving: "self-host, vLLM/NeMo, EU GPU",
    werTelephony: "pending frozen holdout",
    status: "pending",
  },
  {
    model: "openai/whisper-large-v3-turbo",
    family: "Whisper",
    params: "0.8B",
    german: "strong",
    license: "MIT",
    serving: "self-host baseline",
    werTelephony: "pending frozen holdout",
    status: "pending",
  },
  {
    model: "Qwen/Qwen3-TTS-0.6B",
    family: "Qwen3-TTS",
    params: "0.6B",
    german: "good",
    license: "Apache-2.0",
    serving: "self-host candidate",
    werTelephony: "pending MOS + holdout",
    status: "pending",
  },
];

export interface DemoTurn {
  speaker: "citizen" | "agent";
  text: string;
  stateNote: string;
}

export const demoReplay: DemoTurn[] = [
  {
    speaker: "citizen",
    text: "Ich möchte einen Sperrmüll anmelden",
    stateNote: "intent → sperrmüll_anmeldung, phase COLLECTING",
  },
  {
    speaker: "agent",
    text: "Gerne, ich melde den Sperrmüll an. Wie lautet die Straße?",
    stateNote: "question asked (1)",
  },
  {
    speaker: "citizen",
    text: "Es ist die Bergmannstrasse",
    stateNote: "slot street = Bergmannstrasse (provisional)",
  },
  {
    speaker: "citizen",
    text: "Die Nummer ist vierundzwanzig",
    stateNote: "dictated number → 24, digit-expanded WER 0.0",
  },
  {
    speaker: "citizen",
    text: "Sag mal, wann ist das Bürgeramt geöffnet?",
    stateNote: "RAG: 3 evidence chunks, source Karl-Liebknecht-Str. 8",
  },
  {
    speaker: "citizen",
    text: "Nein, falsch, die Straße heißt Müllerstraße",
    stateNote: "targeted correction: street only, number kept",
  },
  {
    speaker: "citizen",
    text: "Ich bestätige das so",
    stateNote: "phase CONFIRMING → EXECUTING → COMPLETED, ticket-1 idempotent",
  },
];

export interface ArchNode {
  id: string;
  label: string;
  detail: string;
  x: number;
  y: number;
  w: number;
  layer: "media" | "speech" | "brain" | "data";
}

export const architecture: ArchNode[] = [
  {
    id: "pstn",
    label: "PSTN / SIP",
    detail: "Phone network. In demo mode replaced by a WebSocket replay transport.",
    x: 0,
    y: 40,
    w: 150,
    layer: "media",
  },
  {
    id: "pipecat",
    label: "Pipecat pipeline",
    detail:
      "Per-call PipelineWorker: VAD segmentation, 20 ms PCM chunks, interruption frames, barge-in generation guards.",
    x: 190,
    y: 40,
    w: 170,
    layer: "media",
  },
  {
    id: "stt",
    label: "STT adapter",
    detail:
      "ContractSTTService: VAD-delimited utterances → SpeechProvider.transcribe. Swap OpenRouter ↔ self-hosted vLLM without touching the pipeline.",
    x: 400,
    y: 0,
    w: 180,
    layer: "speech",
  },
  {
    id: "tts",
    label: "TTS adapter",
    detail:
      "ContractTTSService: streams SpeechProvider.synthesize chunks as TTSAudioRawFrame at 24 kHz.",
    x: 400,
    y: 90,
    w: 180,
    layer: "speech",
  },
  {
    id: "bridge",
    label: "AgentBridge",
    detail:
      "Owns the single-writer CallStateMachine. Barge-in cancels the in-flight turn and bumps generation; stale deltas are dropped.",
    x: 620,
    y: 40,
    w: 170,
    layer: "brain",
  },
  {
    id: "agent",
    label: "pydantic-ai agent",
    detail:
      "The only component allowed to execute tools. Runs on OpenRouter (multi-key registry) or AWS Bedrock via the same LLMProvider protocol.",
    x: 830,
    y: 40,
    w: 190,
    layer: "brain",
  },
  {
    id: "knowledge",
    label: "Knowledge (pgvector + S3)",
    detail:
      "Versioned chunks, German tsvector + HNSW hybrid search, RRF fusion, tenant/service/validity filters. Demo mode: in-memory.",
    x: 620,
    y: 150,
    w: 170,
    layer: "data",
  },
  {
    id: "obs",
    label: "Observability",
    detail:
      "Per-call event flight recorder, Prometheus metrics, OpenTelemetry/Logfire traces. docs/runbook.md maps symptoms to checks.",
    x: 830,
    y: 150,
    w: 190,
    layer: "data",
  },
];

export interface LoadResult {
  requested: number;
  admitted: number;
  rejected: number;
  completedTurns: number;
  p50Ms: number;
  p95Ms: number;
  wallTimeS: number;
}

export const loadResult: LoadResult = {
  requested: 200,
  admitted: 50,
  rejected: 150,
  completedTurns: 250,
  p50Ms: 0.13,
  p95Ms: 0.15,
  wallTimeS: 0.106,
};

export const honestLimitations: string[] = [
  "The 1,000-concurrent-call figure is an engineering target with a ready harness (loadtest/run.py), not a measured result. This laptop has one 8 GB laptop GPU; admission control was verified at 50 concurrent calls with fake providers.",
  "STT/TTS WER and MOS numbers are pending the frozen holdout eval on the GPU box (evals/speech_release.py). Every table row says PENDING rather than showing a fabricated number.",
  "Real OpenRouter/Bedrock smoke tests (evals/provider_smoke.py) need entitled credentials; the code paths are tested against recorded HTTP interactions instead.",
  "SIP telephony is a seam, not an integration. The live demo uses browser WebRTC; LiveKit/SIP wiring is documented in docs/architecture.md.",
  "Public analytics can measure that someone viewed the site, never who they are. No PII is collected by design.",
];

export const runbookExcerpt = [
  { symptom: "Slow replies", firstCheck: "turn_latency_seconds histogram vs flight-recorder waterfall" },
  { symptom: "Talk-over / stale audio", firstCheck: "generation increments; cancelled turn acked" },
  { symptom: "Wrong names or numbers", firstCheck: "replay telephony-degraded audio; WER per scenario" },
  { symptom: "Rate limits / cost spikes", firstCheck: "provider_errors_total by kind; Retry-After honored" },
  { symptom: "Duplicate actions", firstCheck: "tool idempotency record before retry" },
];

export const analyticsEvents = [
  "presentation_started",
  "demo_replay_started",
  "demo_replay_completed",
  "benchmark_downloaded",
  "presentation_completed",
  "contact_link_clicked",
] as const;
