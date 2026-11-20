#!/usr/bin/env bash
# Launch the local server with the installed models on Linux or macOS.
#
# Sources scripts/model-env.sh when external/B-Free exists, so an upload can be
# scored. Without installed weights the server still runs and reports scores as
# missing, which is the intended behaviour.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -d external/B-Free && -f scripts/model-env.sh ]]; then
  # shellcheck source=/dev/null
  source scripts/model-env.sh
fi

PYTHON="python3"
if [[ -x .venv/bin/python ]]; then
  PYTHON=".venv/bin/python"
fi

exec "$PYTHON" -m forensics.server "$@"
