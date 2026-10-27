#!/usr/bin/env python3
"""Optional TruFor runner; emit JSON only for a successfully validated result."""

import argparse
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from forensics.detectors import run_trufor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo", default=os.environ.get("TRUFOR_REPO"))
    parser.add_argument("--python", default=os.environ.get("TRUFOR_PYTHON", sys.executable))
    parser.add_argument("--device", default=os.environ.get("TRUFOR_DEVICE", "cpu"))
    args = parser.parse_args()
    if not args.repo:
        parser.error("Supply --repo or TRUFOR_REPO pointing to the official TruFor checkout.")
    try:
        with redirect_stdout(sys.stderr):
            result = run_trufor(args.image, args.output, args.repo, args.python, args.device)
    except Exception as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
