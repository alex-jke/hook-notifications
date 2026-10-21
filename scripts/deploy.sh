#!/usr/bin/env bash
# Deploy what's on GitHub to the always-on machine and restart the service.
#   scripts/deploy.sh user@thinkpad [remote_dir]
# Or set HOOKS_DEPLOY_HOST (and optionally HOOKS_DEPLOY_DIR) in your shell.
# The remote must already be cloned and set up with ./setup.sh once.
set -euo pipefail
cd "$(dirname "$0")/.."

HOST="${1:-${HOOKS_DEPLOY_HOST:-}}"
DIR="${2:-${HOOKS_DEPLOY_DIR:-hooks}}"
if [[ -z "$HOST" ]]; then
  echo "usage: scripts/deploy.sh user@host [remote_dir]"; exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "warning: you have uncommitted changes; they are NOT deployed"
fi
git fetch -q || true
if [[ "$(git rev-parse @ 2>/dev/null)" != "$(git rev-parse '@{u}' 2>/dev/null)" ]]; then
  echo "warning: local branch differs from GitHub; the remote pulls what is on GitHub (did you push?)"
fi

ssh "$HOST" "set -e; cd '$DIR' \
  && git pull --ff-only \
  && .venv/bin/python -m pip install -q -e . \
  && .venv/bin/hooks init \
  && .venv/bin/hooks check \
  && .venv/bin/hooks service restart \
  && echo deployed: \$(git log -1 --oneline)"
