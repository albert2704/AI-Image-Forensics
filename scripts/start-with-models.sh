#!/bin/bash
set -euo pipefail
FORENSICS_PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$FORENSICS_PROJECT_DIR"
source scripts/model-env.sh
if [[ ! -x .venv/bin/python ]]; then
  printf '%s\n' 'The project Python environment is missing. See docs/MODEL_SETUP.md.' >&2
  exit 1
fi
exec .venv/bin/python -m forensics.server "$@"
