#!/usr/bin/env bash
# Shared process-supervision helpers for start.sh/stop.sh/restart.sh and their
# enterprise/ counterparts.
#
# Background: `(cd "$dir" && eval "$cmd") > log 2>&1 &; echo $!` records the
# PID of the *subshell* bash forked to run the pipeline, not the service
# itself. Normally bash optimizes a subshell's sole/last command by exec'ing
# over the subshell instead of forking again — but every caller here installs
# a `trap ... EXIT INT TERM`, which disables that optimization. So `$!` ends
# up one process hop away from the real service, and with wrapper commands
# that themselves fork a child (`uv run python server.py`; empirically
# verified: `uv` does not exec into its child, it forks one) it's two hops
# away. `kill $recorded_pid` then kills only the subshell/wrapper — the real
# service gets reparented to init and keeps running with its port bound.
#
# Fix, verified experimentally against real services (uv-run MCP servers,
# npm run dev): use `exec` so the backgrounded subshell replaces itself with
# the real process instead of
# forking a layer, AND run every service in its own process group (the
# caller must `set -m` before sourcing/calling into this file) so that even
# a remaining wrapper-forks-a-child hop (uv, npm) can be reaped as a unit via
# a negative-PID (process-group) kill. Callers must `set -m` before starting
# any service — job control is what gives each backgrounded job its own
# process group in a non-interactive script.
#
# Identity check: a pidfile only records a PID, and PIDs get reused —
# especially after a reboot. Before killing anything, supervise_stop
# compares the process's start time (`ps -o lstart=`) against what was
# recorded at start time; a mismatch means the PID was recycled by an
# unrelated process, and supervise_stop refuses to touch it.

# supervise_start <name> <dir> <cmd> <pidfile>
# Runs <cmd> from <dir>, backgrounded, logging to logs/<name>.log (relative
# to the caller's cwd). Writes <pidfile> as two lines: PID, then the
# process's start time (for the identity check in supervise_stop). Appends
# the new PID to the global SUPERVISE_PIDS array for callers that want to
# sweep everything on their own EXIT trap (e.g. start.sh's Ctrl-C handler).
#
# Must be called directly (not via command substitution / a pipeline) so
# `$!` and job control apply in the caller's own shell, not a subshell.
SUPERVISE_PIDS=()

# supervise_record_pid <pid> <pidfile>
# Writes a pidfile in the two-line format supervise_stop expects: the PID,
# then its process start time (for the PID-reuse identity check). Used both
# by supervise_start and by callers recording their own $$ (e.g. start.sh's
# own pid, so stop.sh can identity-check and stop it like everything else).
supervise_record_pid() {
    local pid="$1" pidfile="$2"
    local start_time
    # `|| true` throughout this file: these scripts are sourced into callers
    # running under `set -e`, and a bare `var="$(cmd)"` assignment (unlike
    # one on the same line as `local`) propagates cmd's exit status —  a
    # transient failure here (e.g. querying a pid that's already gone) must
    # not abort the whole start/stop/restart run.
    start_time="$(ps -o lstart= -p "$pid" 2>/dev/null)" || true
    { echo "$pid"; echo "$start_time"; } > "$pidfile"
}

supervise_start() {
    local name="$1" dir="$2" cmd="$3" pidfile="$4"
    # `exec env $cmd` (unquoted $cmd: deliberate word-splitting, no eval) —
    # `env` parses any leading VAR=val words as environment for the command
    # that follows and execs straight into it, so this collapses (cd && exec
    # env cmd) to a single process image instead of forking to run $cmd.
    ( cd "$dir" && exec env $cmd ) > "logs/${name}.log" 2>&1 &
    local pid=$!
    supervise_record_pid "$pid" "$pidfile"
    SUPERVISE_PIDS+=("$pid")
    echo "  [$name] pid $pid — logs/${name}.log"
}

# supervise_stop <pidfile> [label]
# Verifies the PID in <pidfile> is still the same process that was started
# (start-time comparison, guards against PID reuse), then SIGTERMs its whole
# process group, escalating to SIGKILL after a short grace period if
# anything's still alive. Always removes <pidfile>. Prints one status line.
supervise_stop() {
    local pidfile="$1"
    local label="${2:-$(basename "$pidfile" .pid)}"

    if [[ ! -f "$pidfile" ]]; then
        echo "  [$label] no pidfile — already stopped"
        return 0
    fi

    local pid recorded_start current_start
    pid="$(sed -n '1p' "$pidfile")" || true
    recorded_start="$(sed -n '2p' "$pidfile")" || true
    rm -f "$pidfile"

    if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
        echo "  [$label] already stopped"
        return 0
    fi

    current_start="$(ps -o lstart= -p "$pid" 2>/dev/null)" || true
    if [[ -n "$recorded_start" && "$current_start" != "$recorded_start" ]]; then
        echo "  [$label] pid $pid has been reused by another process since it was recorded — leaving it alone"
        return 0
    fi

    # Process-group kill first (catches wrapper-forked children like uv's or
    # npm's); fall back to a plain kill if the group is somehow gone.
    kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true

    local waited=0
    while kill -0 "$pid" 2>/dev/null && [[ $waited -lt 20 ]]; do
        sleep 0.1
        waited=$((waited + 1))
    done

    if kill -0 "$pid" 2>/dev/null; then
        kill -9 -- "-$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
        sleep 0.2
    fi

    if kill -0 "$pid" 2>/dev/null; then
        echo "  [$label] FAILED to stop (pid $pid still alive)"
        return 1
    fi

    echo "  [$label] stopped (pid $pid)"
    return 0
}

# ── Settings, ports, and startup checks ─────────────────────────────────────
#
# Services read their settings through python-dotenv, which never overrides
# a variable already in the environment. env_value applies the same rule so
# the scripts check the ports the services will actually bind: the shell
# environment first, then the last matching line in $ENV_FILE (default
# ./.env), then the given default.

# env_value <var> <default>
env_value() {
    local var="$1" default="$2" value
    if [[ -n "${!var+x}" ]]; then
        echo "${!var}"
        return 0
    fi
    value="$(grep -E "^[[:space:]]*(export[[:space:]]+)?${var}=" "${ENV_FILE:-.env}" 2>/dev/null | tail -1 | cut -d= -f2-)" || true
    value="${value%%[[:space:]]#*}"                 # trailing comment
    value="${value%"${value##*[![:space:]]}"}"       # trailing whitespace
    value="${value%\"}"; value="${value#\"}"
    value="${value%\'}"; value="${value#\'}"
    echo "${value:-$default}"
}

# supervise_render <template> <out>
# Replaces each ${VAR:-default} in <template> with env_value VAR default.
# Every placeholder must carry a default, so a fresh checkout without the
# variable in .env renders the stock value.
supervise_render() {
    local template="$1" out="$2" content full var default
    content="$(<"$template")"
    while [[ "$content" =~ \$\{([A-Za-z_][A-Za-z0-9_]*):-([^}]*)\} ]]; do
        full="${BASH_REMATCH[0]}"
        var="${BASH_REMATCH[1]}"
        default="${BASH_REMATCH[2]}"
        content="${content//"$full"/$(env_value "$var" "$default")}"
    done
    printf '%s\n' "$content" > "$out"
}

# port_listening <port> — true if something accepts TCP connections on
# 127.0.0.1:<port>. bash's /dev/tcp needs no extra tools on macOS or Linux.
port_listening() {
    (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null
}

# port_holder <port> — "pid N (command)" for the process listening on
# <port>, or "an unknown process" if neither lsof nor ss can say.
port_holder() {
    local port="$1" pid=""
    if command -v lsof >/dev/null 2>&1; then
        pid="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -1)" || true
    elif command -v ss >/dev/null 2>&1; then
        pid="$(ss -ltnpH "sport = :$port" 2>/dev/null | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)" || true
    fi
    if [[ -n "$pid" ]]; then
        echo "pid $pid ($(ps -o comm= -p "$pid" 2>/dev/null || echo '?'))"
    else
        echo "an unknown process"
    fi
}

# SUPERVISE_CHECKS: one "name|port" entry per service, port empty for
# services that don't listen. Filled by supervise_expect.
SUPERVISE_CHECKS=()

# supervise_expect <name> [port]
supervise_expect() {
    SUPERVISE_CHECKS+=("$1|${2:-}")
}

# supervise_preflight — fails (status 1) and names the holder of every
# expected port that's already taken. A service started onto a taken port
# dies at once while the old process keeps answering, which looks healthy
# from outside; refusing to start makes the conflict visible.
supervise_preflight() {
    local entry name port conflicts=0
    for entry in "${SUPERVISE_CHECKS[@]}"; do
        name="${entry%%|*}"; port="${entry#*|}"
        [[ -z "$port" ]] && continue
        if port_listening "$port"; then
            echo "  [$name] port $port is already in use by $(port_holder "$port")"
            conflicts=$((conflicts + 1))
        fi
    done
    if [[ $conflicts -gt 0 ]]; then
        echo "Stop whatever holds those ports (often a leftover from an earlier run: ./stop.sh, or kill the pid) and try again."
        return 1
    fi
}

# supervise_verify [timeout_seconds] — after launch, waits for every expected
# service: OK once its port is listening (or, with no port, once it has
# stayed up a few seconds), FAILED if its process exits or the timeout passes.
# Prints the tail of the log for each failure. Status 1 if any failed.
supervise_verify() {
    local timeout="${1:-${SUPERVISE_VERIFY_TIMEOUT:-60}}" waited=0 failed=0
    local pending=("${SUPERVISE_CHECKS[@]}") still entry name port pid
    echo "Checking services..."
    while [[ ${#pending[@]} -gt 0 ]]; do
        still=()
        for entry in "${pending[@]}"; do
            name="${entry%%|*}"; port="${entry#*|}"
            pid="$(sed -n '1p' ".pids/${name}.pid" 2>/dev/null)" || true
            if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
                _supervise_failed "$name" "exited during startup"
                failed=$((failed + 1))
            elif [[ -n "$port" ]] && port_listening "$port"; then
                echo "  [$name] OK (port $port)"
            elif [[ -z "$port" && $waited -ge 3 ]]; then
                echo "  [$name] OK (running)"
            elif [[ $waited -ge $timeout ]]; then
                _supervise_failed "$name" "not listening on port $port after ${timeout}s"
                failed=$((failed + 1))
            else
                still+=("$entry")
            fi
        done
        pending=("${still[@]+"${still[@]}"}")
        [[ ${#pending[@]} -gt 0 ]] && { sleep 1; waited=$((waited + 1)); }
    done
    if [[ $failed -gt 0 ]]; then
        echo "$failed service(s) FAILED to start — see above."
        return 1
    fi
}

_supervise_failed() {
    local name="$1" reason="$2"
    echo "  [$name] FAILED: $reason — last lines of logs/${name}.log:"
    tail -n 5 "logs/${name}.log" 2>/dev/null | sed 's/^/      /'
}
