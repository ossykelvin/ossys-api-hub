#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-8000}"
DRY_RUN=false
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=true
fi

PIDS=()
while IFS= read -r PID; do
  PIDS+=("$PID")
done < <(
  ps -eo pid=,args= | awk -v port="$PORT" '
    /uvicorn/ && /app\.main:app/ && index($0, "--port " port) { print $1 }
  '
)

if [[ ${#PIDS[@]} -eq 0 ]]; then
  echo "Ossy's API Hub is not running on port $PORT."
  exit 0
fi

for PID in "${PIDS[@]}"; do
  if $DRY_RUN; then
    echo "Would stop Ossy's API Hub (PID $PID) on port $PORT."
  else
    kill "$PID"
    echo "Stopped Ossy's API Hub (PID $PID) on port $PORT."
  fi
done
