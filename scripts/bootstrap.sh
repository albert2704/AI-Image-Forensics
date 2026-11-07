#!/usr/bin/env bash
# Create the project environment on Linux or macOS.
#
#   bash scripts/bootstrap.sh            base workflow (Pillow + NumPy)
#   bash scripts/bootstrap.sh --models   add pinned PyTorch/timm/transformers
#
# Re-running is safe: an existing .venv is reused and packages are only
# reinstalled if they are missing or the pins changed.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
WITH_MODELS=0
for argument in "$@"; do
  case "$argument" in
    --models) WITH_MODELS=1 ;;
    *) printf 'Unknown option: %s\n' "$argument" >&2; exit 2 ;;
  esac
done

if [[ ! -x .venv/bin/python ]]; then
  printf 'Creating .venv with %s\n' "$PYTHON"
  "$PYTHON" -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
if [[ "$WITH_MODELS" == 1 ]]; then
  printf 'Installing pinned inference packages.\n'
  .venv/bin/python -m pip install -r requirements-models.txt
fi

printf '\nEnvironment ready. Current state:\n\n'
.venv/bin/python scripts/doctor.py || true

cat <<'NEXT'

Next:
  bash scripts/run.sh                         # http://127.0.0.1:8765, loads external/ models when present
  .venv/bin/python -m unittest discover -s tests
NEXT
