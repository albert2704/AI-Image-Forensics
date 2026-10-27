#!/bin/zsh
set -e
cd "$(dirname "$0")"
if [[ -x .venv/bin/python ]]; then
  if [[ -f scripts/start-with-models.sh ]]; then
    exec bash scripts/start-with-models.sh
  fi
  exec .venv/bin/python -m forensics.server
elif [[ -x /Users/albert/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 ]]; then
  exec /Users/albert/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m forensics.server
else
  exec python3 -m forensics.server
fi
