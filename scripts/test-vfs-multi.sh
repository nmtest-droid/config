#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
script=$(mktemp); trap 'rm -f "$script"' EXIT
printf 'pwd\nls\ncat hello.txt\ncd docs\npwd\nls\ncat guide.txt\nexit\n' > "$script"
python3 shell.py --vfs examples/vfs/multi.csv --prompt 'multi$ ' --startup-script "$script"
