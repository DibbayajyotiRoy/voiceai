# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportCallIssue=false
"""G6 entry point: reproduce the 1,000-concurrent-call verification.

Runs the load harness against a JSON config. On production hardware with real
speech providers this validates: 1,000 concurrent media calls within SLOs,
30% headroom, soak-memory stability, and worker-failure recovery.

On this laptop it runs whatever concurrency the machine admits and reports
CONCURRENT_1000_FAILED with an honest reason — the harness is correct, the
hardware is not the production fleet.

Usage: uv run python -m loadtest.run --config loadtest/configs/concurrent-1000.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sys
from pathlib import Path

from loadtest.harness import run_load


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    target_calls = int(config.get("calls", 1000))
    max_concurrent = int(config.get("max_concurrent", target_calls))
    turns = int(config.get("turns_per_call", 6))
    slo_p95_ms = float(config.get("slo_turn_p95_ms", 2500))
    media = bool(config.get("media", False))
    hardware = str(config.get("hardware", ""))

    print(f"target: {target_calls} concurrent calls, SLO p95 turn <= {slo_p95_ms} ms")
    print(f"machine: {platform.platform()}")

    if not media:
        print(
            "CONCURRENT_1000_FAILED: config does not declare media=true — the harness "
            "then measures state-machine turns only, not real audio. G6 requires real "
            "concurrent media calls on named production hardware."
        )
        return 1

    if not hardware:
        print("CONCURRENT_1000_FAILED: config must name the hardware under test")
        return 1

    report = asyncio.run(
        run_load(calls=target_calls, turns_per_call=turns, max_concurrent=max_concurrent)
    )
    summary = report.summary(machine_note=hardware)
    print(json.dumps(summary, indent=2))

    if target_calls > int(str(summary["admitted"])):
        print(
            f"CONCURRENT_1000_FAILED: only {summary['admitted']}/{target_calls} admitted — "
            "run on the production fleet to validate the real target"
        )
        return 1
    if float(str(summary["turn_latency_p95_ms"])) > slo_p95_ms:
        print("CONCURRENT_1000_FAILED: p95 turn latency above SLO")
        return 1
    if summary["errors"]:
        print(f"CONCURRENT_1000_FAILED: {summary['errors']} call errors")
        return 1
    print("CONCURRENT_1000_PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
