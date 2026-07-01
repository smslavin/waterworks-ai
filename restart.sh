#!/usr/bin/env bash
# Restart a single service without touching the others.
# Usage: ./restart.sh <service>
#
# Note: ./stop.sh will still cleanly stop all services including restarted ones.
# Ctrl-C on the original start.sh will NOT kill a restarted service — use stop.sh instead.
#
# Restart order matters for tool cache correctness:
#   MCP services (audit-mcp, etc.) → aggregator → chat-ui
# If you restart an MCP service, you must also restart aggregator then chat-ui
# so the backend's in-memory tool cache (mcp_client._tool_cache) reflects the new tool list.

set -e
cd "$(dirname "$0")"

SERVICE="$1"
SERVICES="simulator bridge mqtt-mcp opcua-mcp influxdb-mcp audit-mcp control-mcp memory-mcp topology-builder aggregator chat-ui frontend"

if [[ -z "$SERVICE" ]]; then
    echo "Usage: $0 <service>"
    echo "Services: $SERVICES"
    exit 1
fi

# ── Kill existing instance ────────────────────────────────────────────────────

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

# Fallback: pkill any matching process not covered by the PID file
# (catches services started manually outside of start.sh / restart.sh)
case "$SERVICE" in
    chat-ui)          pkill -f "python backend.py"    2>/dev/null || true ;;
    simulator)        pkill -f "python simulator.py"  2>/dev/null || true ;;
    aggregator)       pkill -P "$(pgrep -f 'mcp-aggregator/server' | head -1)" 2>/dev/null || true; kill "$(pgrep -f 'mcp-aggregator/server/.venv')" 2>/dev/null || true ;;
    audit-mcp)        pkill -f "audit-mcp/server.py"  2>/dev/null || true ;;
    control-mcp)      pkill -f "control-mcp/server.py" 2>/dev/null || true ;;
    memory-mcp)       pkill -f "memory-mcp/server.py" 2>/dev/null || true ;;
esac
sleep 0.5

# ── Restart ───────────────────────────────────────────────────────────────────

mkdir -p logs .pids

start_one() {
    local name="$1" dir="$2" cmd="$3"
    (cd "$dir" && eval "$cmd") > "logs/${name}.log" 2>&1 &
    local pid=$!
    echo "$pid" > ".pids/${name}.pid"
    echo "  [$name] started — pid $pid — logs/${name}.log"
}

case "$SERVICE" in
    simulator)        start_one simulator        simulator              "uv run python simulator.py" ;;
    bridge)           start_one bridge            mqtt-influx-bridge    "uv run python bridge.py" ;;
    mqtt-mcp)         start_one mqtt-mcp          mcp-servers/mqtt-mcp  "uv run python server.py" ;;
    opcua-mcp)        start_one opcua-mcp         mcp-servers/opcua-mcp "uv run python server.py" ;;
    influxdb-mcp)     start_one influxdb-mcp      influxdb-mcp          "uv run python server.py" ;;
    audit-mcp)        start_one audit-mcp         audit-mcp             "uv run python server.py" ;;
    control-mcp)      start_one control-mcp       control-mcp           "uv run python server.py" ;;
    memory-mcp)       start_one memory-mcp        memory-mcp            "uv run python server.py" ;;
    topology-builder) start_one topology-builder  topology-builder      "uv run python server.py" ;;
    aggregator)       start_one aggregator        mcp-aggregator/server "uv run python server.py" ;;
    chat-ui)          start_one chat-ui           chat-ui               "uv run python backend.py" ;;
    frontend)         start_one frontend          chat-ui/frontend      "npm run dev" ;;
    *)
        echo "Unknown service: $SERVICE"
        echo "Services: $SERVICES"
        exit 1
        ;;
esac
