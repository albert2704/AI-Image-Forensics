#!/bin/zsh
set -e
cd "$(dirname "$0")"
if [[ -x .venv/bin/python ]]; then
  if [[ -f scripts/start-with-models.sh ]]; then
    exec bash scripts/start-with-models.sh
  fi
  exec .venv/bin/python -m forensics.server
else
  exec python3 -m forensics.server
fi
