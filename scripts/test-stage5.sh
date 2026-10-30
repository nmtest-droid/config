#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python -m unittest discover -s tests -v
python shell.py -v examples/vfs/multi.csv -p 'stage5$ ' -s examples/startup-stage5.sh </dev/null
