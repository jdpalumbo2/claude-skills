#!/usr/bin/env bash
# The clodex catalogue's committed test harness (debt #3, committed at last).
#
# Layers, in order:
#   1. the state engine's contract suite (skills/clodex/state/test_clodex_state.py)
#   2. the runner's own checks (skills/clodex/runner/test_runner.sh), when codex
#      is not required — the runner tests stub the codex binary themselves
#   3. the exploit+control checks in this directory: every behavioral change to
#      the engine, runner, or a stage skill's executable fragment adds a pair
#      here — one check that reproduced the old failure, one that proves the
#      fix holds without overcorrecting.
#
# Usage: tests/run.sh [-v]

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

VERBOSITY="-q"
[ "${1:-}" = "-v" ] && VERBOSITY="-v"

echo "== state engine contract suite =="
python3 -m unittest discover -s skills/clodex/state "$VERBOSITY"

echo "== runner checks =="
bash skills/clodex/runner/test_runner.sh

echo "== exploit+control checks =="
python3 -m unittest discover -s tests "$VERBOSITY"

echo "run.sh: all layers green"
