#!/usr/bin/env bash
# Start the enterprise layer (diagnose_plant_mcp + query_history_mcp +
# orchestrator).
# Reads enterprise.yaml at repo root — expects the plants it lists to already
# be running (their chat-ui/aggregator URLs). Logs go to logs/<service>.log.

set -e
cd "$(dirname "$0")"

mkdir -p logs .pids
echo $$ > .pids/start.pid

PIDS=()
cleanup() {
    echo ""
    echo "Stopping enterprise services..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    rm -f .pids/*.pid
    echo "Done."
}
trap cleanup EXIT INT TERM

start_service() {
    local name="$1"
    local dir="$2"
    local cmd="$3"
    (cd "$dir" && eval "$cmd") > "logs/${name}.log" 2>&1 &
    local pid=$!
    PIDS+=($pid)
    echo "$pid" > ".pids/${name}.pid"
    echo "  [$name] pid $pid — logs/${name}.log"
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
