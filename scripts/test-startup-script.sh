#!/usr/bin/env bash
# Test startup script execution and error handling.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$ROOT/shell.py" --vfs "$ROOT" --prompt 'script@machine:/$ ' \
  --startup-script "$ROOT/examples/startup-errors.sh" </dev/null
