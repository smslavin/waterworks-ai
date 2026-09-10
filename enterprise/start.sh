#!/usr/bin/env bash
# Start the enterprise layer (diagnose_plant_mcp + query_history_mcp +
# orchestrator).
# Reads enterprise.yaml at repo root — expects the plants it lists to already
# be running (their chat-ui/aggregator URLs). Logs go to logs/<service>.log.

set -e
set -m  # each backgrounded service gets its own process group — see ../scripts/lib/supervise.sh
cd "$(dirname "$0")"
source ../scripts/lib/supervise.sh

mkdir -p logs .pids
supervise_record_pid $$ .pids/start.pid

cleanup() {
    echo ""
    echo "Stopping enterprise services..."
    for pid in "${SUPERVISE_PIDS[@]}"; do
        # Group-kill: reaps wrapper-forked children too — see ../scripts/lib/supervise.sh.
        kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
    done
    rm -f .pids/*.pid
    echo "Done."
}
trap cleanup EXIT INT TERM

start_service() {
    supervise_start "$1" "$2" "$3" ".pids/${1}.pid"
}

echo "Starting enterprise services..."
start_service "diagnose-plant-mcp" "diagnose_plant_mcp" "uv run python server.py"
start_service "query-history-mcp" "query_history_mcp" "uv run python server.py"
sleep 1  # give diagnose_plant_mcp a head start before the orchestrator's first list_mcp_tools()
start_service "enterprise-orchestrator" "orchestrator" "uv run python backend.py"

echo ""
echo "Enterprise orchestrator → http://localhost:8020"
echo "Logs: logs/<service>.log  |  Ctrl-C to stop everything."
echo ""

wait
