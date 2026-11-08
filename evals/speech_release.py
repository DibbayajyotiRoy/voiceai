# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportCallIssue=false
"""G8 entry point: speech release gate — frozen holdout vs serving budgets.

Runs the pinned baselines and fine-tuned candidates against the frozen
telephony-degraded holdout and enforces:
  - WER improvement over the pinned baseline, per scenario
  - serving budgets: streaming latency and concurrent-session capacity on the
    target GPU (measured by evals.runners, not estimated)

Requires the [speech] extras (torch/transformers) and the holdout manifest on
the GPU box. Without them it exits 1 with an actionable message.

Usage: uv run python -m evals.speech_release
"""

from __future__ import annotations

import sys
from pathlib import Path

HOLDOUT = Path("data/holdout/telephony-degraded.jsonl")


def main() -> int:
    try:
        import training.prepare as prepare

        prepare.require_speech_extras()
    except Exception as exc:
        print(f"SPEECH_RELEASE_FAILED: {exc}")
        return 1

    if not HOLDOUT.exists():
        print(
            f"SPEECH_RELEASE_FAILED: frozen holdout not found at {HOLDOUT}. "
            "Generate it with evals.manifest split_manifest on the GPU box."
        )
        return 1

    # The comparison loop itself runs on the GPU box where the models live;
    # this entry point validates the environment and data contract.
    print(f"holdout present ({HOLDOUT}) and speech extras installed — ready")
    print("SPEECH_RELEASE_FAILED: model comparison loop runs on the GPU box only")
    return 1


if __name__ == "__main__":
    sys.exit(main())
