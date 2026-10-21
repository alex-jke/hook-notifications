#!/usr/bin/env bash
# One-time (and safe to re-run) setup on a new machine:
#   ./setup.sh          runtime install (e.g. the ThinkPad)
#   ./setup.sh --dev    also installs pytest + ruff (e.g. your Mac)
set -euo pipefail
cd "$(dirname "$0")"

EXTRAS=""
[[ "${1:-}" == "--dev" ]] && EXTRAS="[dev]"
PY="${PYTHON:-python3}"

if ! "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
  echo "error: Python >= 3.10 needed, found: $("$PY" --version 2>&1 || echo none)"
  echo "       (macOS: brew install python   |   set PYTHON=/path/to/python3.x to override)"
  exit 1
fi

if [[ ! -d .venv ]]; then
  echo "==> creating virtualenv in .venv"
  if ! "$PY" -m venv .venv; then
    echo "error: venv failed. On Ubuntu: sudo apt install python3-venv"
    exit 1
  fi
fi

echo "==> installing hooks${EXTRAS}"
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -e ".${EXTRAS}"

echo "==> creating per-machine files (git-ignored)"
.venv/bin/hooks init

cat <<'EOF'

Next steps:
  1. Fill in the secrets in .env, adjust config.yaml for this machine
  2. .venv/bin/hooks check           validate
  3. .venv/bin/hooks test            phone should buzz
  4. .venv/bin/hooks run --dry-run   watch real messages, send nothing (Ctrl-C to stop)
  5. .venv/bin/hooks service install run in the background (systemd / launchd)
EOF
