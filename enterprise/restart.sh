#!/usr/bin/env bash
# Restart a single enterprise service without touching the other.
# Usage: ./restart.sh <service>

set -e
cd "$(dirname "$0")"
ROOT="$(pwd)"

SERVICE="$1"
SERVICES="diagnose-plant-mcp query-history-mcp enterprise-orchestrator"

if [[ -z "$SERVICE" ]]; then
    echo "Usage: $0 <service>"
    echo "Services: $SERVICES"
    exit 1
fi

PID_FILE=".pids/${SERVICE}.pid"
if [[ -f "$PID_FILE" ]]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping $SERVICE (pid $OLD_PID)..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
    fi
    rm -f "$PID_FILE"
fi

# Fallback pkill, anchored on $ROOT so it can't kill another checkout's
# same-named service — see waterworks-ai/restart.sh for the full rationale.
case "$SERVICE" in
    diagnose-plant-mcp)      pkill -f "${ROOT}/diagnose_plant_mcp/.venv" 2>/dev/null || true ;;
    query-history-mcp)       pkill -f "${ROOT}/query_history_mcp/.venv" 2>/dev/null || true ;;
    enterprise-orchestrator) pkill -f "${ROOT}/orchestrator/.venv"       2>/dev/null || true ;;
esac
sleep 0.5

mkdir -p logs .pids

start_one() {
    local name="$1" dir="$2" cmd="$3"
    (cd "$dir" && eval "$cmd") > "logs/${name}.log" 2>&1 &
    local pid=$!
    echo "$pid" > ".pids/${name}.pid"
    echo "  [$name] started — pid $pid — logs/${name}.log"
}

case "$SERVICE" in
    diagnose-plant-mcp)      start_one diagnose-plant-mcp      diagnose_plant_mcp "uv run python server.py" ;;
    query-history-mcp)       start_one query-history-mcp       query_history_mcp  "uv run python server.py" ;;
    enterprise-orchestrator) start_one enterprise-orchestrator orchestrator       "uv run python backend.py" ;;
    *)
        echo "Unknown service: $SERVICE"
        echo "Services: $SERVICES"
        exit 1
        ;;
esac
