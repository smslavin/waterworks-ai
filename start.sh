#!/usr/bin/env bash
# Start all waterworks-ai services.
# Logs go to logs/<service>.log. Ctrl-C stops everything.

set -e
set -m  # each backgrounded service gets its own process group — see scripts/lib/supervise.sh
cd "$(dirname "$0")"
source scripts/lib/supervise.sh

# mcp-aggregator/server ships its own bundled .env (AGGREGATOR_PORT=8100, for the
# submodule's standalone mock/testing use) — python-dotenv's load_dotenv() finds
# that one first walking up from the aggregator's cwd and never reaches this
# checkout's real root .env, since it doesn't override already-set vars. Read the
# real value here and pass it explicitly so a second checkout (M10 multi-plant)
# with a different AGGREGATOR_PORT isn't silently shadowed back to 8100.
AGGREGATOR_PORT="$(grep -E '^AGGREGATOR_PORT=' .env 2>/dev/null | tail -1 | cut -d= -f2)"
AGGREGATOR_PORT="${AGGREGATOR_PORT:-8100}"

mkdir -p logs .pids
supervise_record_pid $$ .pids/start.pid

cleanup() {
    echo ""
    echo "Stopping all services..."
    for pid in "${SUPERVISE_PIDS[@]}"; do
        # Group-kill: reaps wrapper-forked children (uv, npm) too, not just
        # the recorded PID. See scripts/lib/supervise.sh for why.
        kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
    done
    rm -f .pids/*.pid
    echo "Done."
}
trap cleanup EXIT INT TERM

start_service() {
    supervise_start "$1" "$2" "$3" ".pids/${1}.pid"
}

# ── Expected services and their ports (this checkout's .env, then defaults) ──
supervise_expect simulator        "$(env_value CONTROL_PORT 8090)"
supervise_expect bridge
supervise_expect influxdb-mcp     "$(env_value INFLUXDB_MCP_PORT 8003)"
supervise_expect audit-mcp        "$(env_value AUDIT_MCP_PORT 8004)"
supervise_expect control-mcp      "$(env_value CONTROL_MCP_PORT 8005)"
supervise_expect memory-mcp       "$(env_value MEMORY_MCP_PORT 8006)"
supervise_expect topology-builder "$(env_value TOPOLOGY_BUILDER_PORT 8007)"
supervise_expect aggregator       "$AGGREGATOR_PORT"
supervise_expect chat-ui          "$(env_value CHAT_UI_PORT 8080)"
supervise_expect frontend   # Vite moves to the next free port when 5173 is taken

echo "Checking ports..."
supervise_preflight || exit 1

# The aggregator gets this checkout's backend ports from .env, rendered into an
# untracked copy of the tracked template — a second plant (M10) needs no edit
# to a tracked file.
supervise_render mcp-aggregator/backends.json mcp-aggregator/backends.rendered.json

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
sleep 2  # head start for the backends; the aggregator retries any it misses
# aggregator spawns mqtt-mcp/opcua-mcp itself as stdio subprocesses (see
# backends.json) — no separate start_service entries for them. BACKENDS_FILE
# and AGGREGATOR_PORT must be set explicitly: the aggregator's own defaults
# resolve to the submodule's bundled example config, not this checkout's.
start_service "aggregator" "mcp-aggregator/server" "BACKENDS_FILE=../backends.rendered.json AGGREGATOR_PORT=${AGGREGATOR_PORT} uv run python server.py"
start_service "chat-ui"          "chat-ui"            "uv run python backend.py"
start_service "frontend"         "chat-ui/frontend"   "npm run dev"

echo ""
supervise_verify || true   # keep whatever did start running; failures are listed above
echo ""
echo "Chat UI → http://localhost:$(env_value CHAT_UI_PORT 8080)  |  Vite dev UI → see logs/frontend.log"
echo "Logs: logs/<service>.log  |  Ctrl-C to stop everything."
echo ""

wait
