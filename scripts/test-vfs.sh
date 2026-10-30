#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
printf 'pwd\nls\nexit\n' | python3 "$ROOT/shell.py" --vfs "$ROOT/examples/vfs/minimal.csv"
