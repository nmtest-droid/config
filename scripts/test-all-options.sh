#!/usr/bin/env bash
# Test all three command-line parameters together.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$ROOT/shell.py" --vfs "$ROOT" --prompt 'all@options:/$ ' \
  --startup-script "$ROOT/examples/startup-success.sh" </dev/null
