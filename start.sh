#!/usr/bin/env bash
# Start all waterworks-ai services.
# Logs go to logs/<service>.log. Ctrl-C stops everything.

set -e
cd "$(dirname "$0")"

mkdir -p logs .pids
echo $$ > .pids/start.pid

PIDS=()
cleanup() {
    echo ""
    echo "Stopping all services..."
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

# ── Infrastructure ───────────────────────────────────────────────────────────
echo "Starting infrastructure..."
docker compose up -d --quiet-pull
echo "  [docker] mosquitto + influxdb + grafana"
sleep 2  # give brokers time to be ready

# ── Services ─────────────────────────────────────────────────────────────────
echo "Starting services..."
start_service "simulator"        "simulator"          "uv run python simulator.py"
start_service "bridge"           "mqtt-influx-bridge" "uv run python bridge.py"
start_service "mqtt-mcp"         "mcp-servers/mqtt-mcp"  "uv run python server.py"
start_service "opcua-mcp"        "mcp-servers/opcua-mcp" "uv run python server.py"
start_service "influxdb-mcp"     "influxdb-mcp"       "uv run python server.py"
start_service "audit-mcp"        "audit-mcp"          "uv run python server.py"
start_service "control-mcp"      "control-mcp"        "uv run python server.py"
start_service "memory-mcp"       "memory-mcp"         "uv run python server.py"
start_service "topology-builder" "topology-builder"   "uv run python server.py"
start_service "aggregator"       "mcp-aggregator/server" "uv run python server.py"
start_service "chat-ui"          "chat-ui"            "uv run python backend.py"
start_service "frontend"         "chat-ui/frontend"   "npm run dev"

echo ""
echo "All services running. Chat UI (legacy) → http://localhost:8000  |  Vue UI → http://localhost:5173"
echo "Logs: logs/<service>.log  |  Ctrl-C to stop everything."
echo ""

wait
