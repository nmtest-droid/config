#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 -m unittest discover -s tests -v
python3 shell.py -v examples/vfs/multi.csv -p 'stage4$ ' -s examples/startup-stage4.sh </dev/null
