#!/usr/bin/env bash
# Test default VFS and OS-generated prompt (no startup script).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$ROOT/shell.py" </dev/null
