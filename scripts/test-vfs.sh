#!/usr/bin/env bash
# Test the physical VFS path parameter.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$ROOT/shell.py" --vfs "$ROOT" </dev/null
