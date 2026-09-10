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
