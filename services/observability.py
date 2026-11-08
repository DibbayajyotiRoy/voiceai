"""Observability wiring: Logfire/OTel tracing + Prometheus metrics.

- Tracing is configured from the environment and is a no-op without
  LOGFIRE_TOKEN (local dev stays offline).
- Prometheus counters/histograms always work; they are the first thing to
  check when a call misbehaves (see docs/runbook.md).
"""

from __future__ import annotations

import os

from loguru import logger
from prometheus_client import Counter, Histogram

calls_started = Counter(
    "voice_calls_started_total", "Calls admitted by the session manager", ["tenant"]
)
calls_rejected = Counter(
    "voice_calls_rejected_total",
    "Calls rejected with fast busy (at capacity)",
    ["tenant"],
)
turn_latency = Histogram(
    "voice_turn_latency_seconds",
    "User turn -> final assistant delta latency",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0],
)
provider_errors = Counter(
    "voice_provider_errors_total",
    "Provider errors by component and kind",
    ["component", "kind"],
)
stt_wer = Histogram(
    "voice_stt_wer",
    "STT word error rate per final transcript (sampled eval traffic)",
    buckets=[0.0, 0.05, 0.1, 0.2, 0.4, 1.0],
)


def configure_tracing(service_name: str = "municipal-voiceai") -> bool:
    """Configure Logfire + OTel. Returns True if a backend was configured."""
    token = os.environ.get("LOGFIRE_TOKEN")
    try:
        import logfire

        logfire.configure(
            token=token,
            service_name=service_name,
            send_to_logfire=bool(token),
            console=False,
        )
        logfire.instrument_httpx()
        logger.info("tracing configured (backend={})", "logfire" if token else "none")
        return bool(token)
    except Exception as exc:  # tracing must never break the service
        logger.warning("tracing configuration failed, continuing without: {}", exc)
        return False
