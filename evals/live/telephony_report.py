"""Combine telephony latency runs without hiding missing or failed turns."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evals.live.telephony import latency_summary


def combine_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    results = [result for report in reports for result in report.get("results", [])]
    requested = sum(
        int(report.get("summary", {}).get("requested_turns", len(report.get("results", []))))
        for report in reports
    )
    summary = latency_summary(results, requested_turns=requested)
    return {
        "measurement_scope": "twilio_dialed_e2e",
        "runs": [report.get("call_sid") for report in reports],
        "status": "completed" if summary["valid_turns"] == requested else "failed",
        "summary": summary,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    reports = [json.loads(path.read_text()) for path in args.reports]
    combined = combine_reports(reports)
    rendered = json.dumps(combined, indent=2)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n")
    print(rendered)
    if combined["status"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
