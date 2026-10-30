#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
printf 'ls\nexit\n' | python3 "$ROOT/shell.py" --prompt 'demo@machine:/$ ' --vfs "$ROOT/examples/vfs/multi.csv"
