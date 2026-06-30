#!/usr/bin/env bash
# Start MCP servers on the host (:8001–8005). Requires .env and data stores up.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
set -a
# shellcheck disable=SC1091
source .env
set +a
export AUTH_ALLOW_ANONYMOUS="${AUTH_ALLOW_ANONYMOUS:-false}"

PIDS=()
start() {
  local name=$1 script=$2 port=$3
  if [[ ! -f "$script" ]]; then
    echo "[skip] $name — $script not found"
    return
  fi
  if lsof -ti ":$port" >/dev/null 2>&1; then
    echo "[skip] :$port already in use ($name)"
    return
  fi
  echo "[start] $name on :$port"
  uv run python "$script" &
  PIDS+=($!)
}

start vitals_trends backend/servers/vitals_trends/main.py 8001
start labs_diagnoses backend/servers/labs_diagnoses/main.py 8002
start medications_interactions backend/servers/medications_interactions/main.py 8003
start clinical_notes_search backend/servers/clinical_notes_search/main.py 8004
start radiology_reports backend/servers/radiology_reports/main.py 8005

cleanup() {
  echo
  echo "[stop] shutting down MCP servers..."
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

echo "[wait] warming up..."
for port in 8001 8002 8003 8004 8005; do
  for _ in $(seq 1 30); do
    if curl -sf "http://localhost:$port/health" >/dev/null 2>&1; then
      echo "[ready] :$port"
      break
    fi
    sleep 0.5
  done
done

if [[ "${1:-}" == "--verify" ]]; then
  uv run python scripts/pre_push_verify.py
  exit $?
fi

echo "[running] MCP servers up (:8001–8005). Ctrl+C to stop."
wait
