# Debugging runbook

Start with the `call_id`, then inspect its ordered event waterfall. Preserve `turn_id`, `generation`, `attempt_id`, provider/model aliases, and monotonic timestamps. Never log secrets or raw personal information.

## Slow replies

1. Compare caller speech end, endpoint decision, LLM first token, TTS first audio, and playback.
2. Separate queueing, network, inference, retrieval, tools, transcoding, and buffering.
3. Check provider route, batch window, GPU utilization, RTP jitter, and stale caches.
4. Replay the same audio with the pinned configuration before changing a model.

## Talk-over or stale audio

1. Inspect VAD/echo events and the barge-in timestamp.
2. Verify generation increment, LLM/TTS cancellation acknowledgement, and queue clearing.
3. Compare spoken assistant text with the context aggregator.
4. Reject late frames from older generations.

## Wrong names or numbers

1. Replay original and telephone-degraded audio.
2. Compare STT candidates, normalization, entity confidence, and dictionary matching.
3. Confirm critical values explicitly; do not freely rewrite them with an LLM.
4. Add a labeled regression before considering fine-tuning data.

## Rate limits or cost spikes

1. Separate OpenRouter global/upstream errors and Bedrock account/Region throttling.
2. Inspect safe key alias, model/profile, attempts, retry amplification, tokens/audio, and budget state.
3. Honor `Retry-After` and the shared retry/deadline budget.
4. Do not add keys as a substitute for capacity engineering.

## Duplicate or truncated actions

1. Inspect stream failures and finalization/correction events.
2. Check tool idempotency record and known execution state before retrying.
3. Discard stale tool arguments from cancelled generations.
4. Verify that the caller received the tool result.

## OOM or resource leak

1. Correlate batch size, context/audio length, CUDA memory, queue depth, and active tasks.
2. Check cleanup after disconnect, cancellation, and provider errors.
3. Compare against soak-test growth and reduce admission before queues become unbounded.

## Knowledge or scope failure

1. Inspect the resolved query and current state.
2. Verify tenant, authorization, validity, language, and publication filters.
3. Trace selected source chunks and document versions.
4. If evidence is absent or outside scope, clarify or hand off rather than inventing an answer.

## Required fault injection

Cover provider timeout/429/5xx, mid-stream disconnect, malformed stream, slow tools, duplicate events, packet loss/jitter, key rotation/exhaustion, GPU worker kill, node loss, and graceful shutdown. Alerts should link to the filtered call trace and this runbook.
