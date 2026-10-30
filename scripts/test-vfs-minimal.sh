#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
script=$(mktemp); trap 'rm -f "$script"' EXIT
printf 'pwd\nls\ncat README.txt\nexit\n' > "$script"
python3 shell.py -v examples/vfs/minimal.csv -p 'minimal$ ' -s "$script"
