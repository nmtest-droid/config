#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 shell.py -v examples/vfs/deep.csv -p 'stage3$ ' -s examples/startup-stage3.sh
