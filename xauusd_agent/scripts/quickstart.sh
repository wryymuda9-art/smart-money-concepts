#!/usr/bin/env bash
#
# quickstart.sh — turnkey: set up deps, pull free real XAUUSD history, print the
# verdict. Run this ON YOUR OWN MACHINE (it needs internet access to the data
# provider, which a CI/cloud sandbox usually blocks).
#
# Usage:
#   git clone <this repo> && cd smart-money-concepts
#   ./xauusd_agent/scripts/quickstart.sh                 # Dukascopy, ~3yr M15
#   ./xauusd_agent/scripts/quickstart.sh -b 2020-01-01   # more history
#
# Requirements it checks/installs for you:
#   - Python 3 + pandas/numpy/numba + this package (pip install -e .)
#   - Node.js (only for the Dukascopy source) — install from https://nodejs.org
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"
PY="${PYTHON:-python3}"

echo "==> checking Python deps"
if ! "$PY" -c "import pandas, numpy, numba, smartmoneyconcepts" >/dev/null 2>&1; then
  echo "    installing (pip install -e .) ..."
  "$PY" -m pip install -e . >/dev/null
fi

echo "==> checking Node (for Dukascopy)"
if ! command -v npx >/dev/null 2>&1; then
  cat >&2 <<'EOF'
    Node.js not found. Either:
      - install it from https://nodejs.org  (then re-run this), or
      - use a free MT5 demo instead (Windows): see xauusd_agent/DATA.md Option C.
EOF
  exit 1
fi

echo "==> fetching real data + running the verdict (this can take a minute)"
exec "$HERE/get_and_validate.sh" --source dukascopy "$@"
