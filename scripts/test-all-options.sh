#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$ROOT/shell.py" -v "$ROOT/examples/vfs/deep.csv" -p 'all@options:/$ ' \
  -s "$ROOT/examples/startup-stage3.sh" </dev/null
