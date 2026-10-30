#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Ожидаем код 2 и сообщение об ошибке загрузки.
if python3 shell.py -v examples/vfs/does-not-exist.csv </dev/null; then
  echo 'ERROR: missing VFS unexpectedly loaded' >&2; exit 1
else
  status=$?
  [[ "$status" -eq 2 ]]
fi
