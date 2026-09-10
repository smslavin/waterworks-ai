#!/usr/bin/env bash
# Restart a single enterprise service without touching the other.
# Usage: ./restart.sh <service>

set -e
set -m  # each backgrounded service gets its own process group — see ../scripts/lib/supervise.sh
cd "$(dirname "$0")"
ROOT="$(pwd)"
source ../scripts/lib/supervise.sh

SERVICE="$1"
SERVICES="diagnose-plant-mcp query-history-mcp enterprise-orchestrator"

if [[ -z "$SERVICE" ]]; then
    echo "Usage: $0 <service>"
    echo "Services: $SERVICES"
    exit 1
fi

# supervise_stop identity-checks the recorded PID (start-time comparison)
# and group-kills it (SIGTERM, then SIGKILL after a grace period), reaping
# wrapper-forked children too — see ../scripts/lib/supervise.sh. Makes the
# old pkill-by-checkout-path fallback unnecessary.
PID_FILE=".pids/${SERVICE}.pid"
supervise_stop "$PID_FILE" "$SERVICE"

mkdir -p logs .pids

start_one() {
    supervise_start "$1" "$2" "$3" ".pids/${1}.pid"
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
