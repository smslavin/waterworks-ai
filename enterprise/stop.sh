#!/usr/bin/env bash
# Stop all enterprise services started by start.sh.

cd "$(dirname "$0")"

if [ ! -d .pids ] || [ -z "$(ls .pids/*.pid 2>/dev/null)" ]; then
    echo "No running enterprise services found (.pids/ is empty)."
    exit 0
fi

echo "Stopping enterprise services..."
for pidfile in .pids/*.pid; do
    name=$(basename "$pidfile" .pid)
    pid=$(cat "$pidfile")
    if kill "$pid" 2>/dev/null; then
        echo "  [$name] stopped (pid $pid)"
    else
        echo "  [$name] already stopped"
    fi
    rm -f "$pidfile"
done

if [[ -f .pids/start.pid ]]; then
    kill "$(cat .pids/start.pid)" 2>/dev/null || true
    rm -f .pids/start.pid
fi

echo "Done."
