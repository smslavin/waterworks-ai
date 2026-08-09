#!/usr/bin/env bash
# Start all waterworks-ai services.
# Logs go to logs/<service>.log. Ctrl-C stops everything.

set -e
cd "$(dirname "$0")"

# mcp-aggregator/server ships its own bundled .env (AGGREGATOR_PORT=8100, for the
# submodule's standalone mock/testing use) — python-dotenv's load_dotenv() finds
# that one first walking up from the aggregator's cwd and never reaches this
# checkout's real root .env, since it doesn't override already-set vars. Read the
# real value here and pass it explicitly so a second checkout (M10 multi-plant)
# with a different AGGREGATOR_PORT isn't silently shadowed back to 8100.
AGGREGATOR_PORT="$(grep -E '^AGGREGATOR_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2)"
AGGREGATOR_PORT="${AGGREGATOR_PORT:-8100}"

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
start_service "influxdb-mcp"     "influxdb-mcp"       "uv run python server.py"
start_service "audit-mcp"        "audit-mcp"          "uv run python server.py"
start_service "control-mcp"      "control-mcp"        "uv run python server.py"
start_service "memory-mcp"       "memory-mcp"         "uv run python server.py"
start_service "topology-builder" "topology-builder"   "uv run python server.py"

sleep 2  # give the backend MCP servers above a head start — aggregator discovery
         # below is one-shot at startup with no retry; a backend not yet listening
         # when discovery runs is silently skipped for the rest of the process

# aggregator spawns mqtt-mcp/opcua-mcp itself as stdio subprocesses (see backends.json) —
# no separate start_service entries for them. BACKENDS_FILE and AGGREGATOR_PORT must
# be set explicitly: the aggregator's own defaults resolve to the submodule's bundled
# example config, not this checkout's real one.
start_service "aggregator" "mcp-aggregator/server" "BACKENDS_FILE=../backends.json AGGREGATOR_PORT=${AGGREGATOR_PORT} uv run python server.py"
start_service "chat-ui"          "chat-ui"            "uv run python backend.py"
start_service "frontend"         "chat-ui/frontend"   "npm run dev"

echo ""
echo "All services running. Chat UI (legacy) → http://localhost:8000  |  Vue UI → http://localhost:5173"
echo "Logs: logs/<service>.log  |  Ctrl-C to stop everything."
echo ""

wait
