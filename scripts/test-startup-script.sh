#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$ROOT/shell.py" -v "$ROOT/examples/vfs/multi.csv" -p 'script@machine:/$ ' \
  -s "$ROOT/examples/startup-stage3.sh" </dev/null
