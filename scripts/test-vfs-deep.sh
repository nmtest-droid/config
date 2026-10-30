#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
script=$(mktemp); trap 'rm -f "$script"' EXIT
printf 'cd home/student/projects/demo\npwd\nls\ncat main.py\ncd data\ncat message.txt\nexit\n' > "$script"
python3 shell.py -v examples/vfs/deep.csv -p 'deep$ ' -s "$script"
