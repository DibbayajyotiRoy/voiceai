"""Fine-tuning entry point (runs on the GPU box, not in CI).

Usage: python -m training.finetune --model parakeet-tdt-0.6b-v3 --base <hf-id> \
          --output runs/parakeet --data data/train.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from training.prepare import require_speech_extras


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--data", required=True)
    args = parser.parse_args()

    require_speech_extras()  # raises with actionable message if extras missing

    data = Path(args.data)
    if not data.exists():
        raise SystemExit(f"training manifest not found: {data}")

    # The actual HF Trainer loop is intentionally not vendored here; each model
    # family has its own recipe on the GPU box. This entry point validates the
    # environment and hands off.
    count = sum(1 for _ in data.open(encoding="utf-8"))
    print(json.dumps({"status": "ready", "samples": count, "model": args.model}))


if __name__ == "__main__":
    main()
