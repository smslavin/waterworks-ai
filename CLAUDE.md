# waterworks-ai

Open source industrial AI demo stack: natural language diagnostics for a simulated water treatment plant using only open source components and public protocols. Reference implementation of the Fieldworks framework.

## Starting the stack

```bash
# 1. Infrastructure (Mosquitto :1883, InfluxDB :8086, Grafana :3000)
docker compose up -d

# 2. Submodules (if not yet initialized)
git submodule update --init --recursive

# 3. Each service — run in separate terminals from its directory with uv:
cd simulator         && uv run python simulator.py
cd mqtt-influx-bridge && uv run python bridge.py
cd mcp-servers/mqtt-mcp   && uv run python server.py
cd mcp-servers/opcua-mcp  && uv run python server.py
cd influxdb-mcp      && uv run python server.py
cd audit-mcp         && uv run python server.py
cd control-mcp       && uv run python server.py
cd memory-mcp        && uv run python server.py
cd topology-builder  && uv run python server.py
cd mcp-aggregator/server && uv run python server.py
cd chat-ui           && uv run python backend.py
```

Chat UI: http://localhost:8000  
Dashboard overview: open `dashboard.html` in browser.

## Port map

| Service | Port |
|---|---|
| Chat UI | 8000 |
| mqtt-mcp | 8001 |
| opcua-mcp | 8002 |
| influxdb-mcp | 8003 |
| audit-mcp | 8004 |
| control-mcp | 8005 |
| memory-mcp | 8006 |
| topology-builder | 8007 |
| mcp-aggregator | 8100 |
| Simulator HTTP (fault/setpoint) | 8090 |
| OPC-UA | 4840 |
| Mosquitto MQTT | 1883 |
| InfluxDB | 8086 |
| Grafana | 3000 |

## Repo structure

```
simulator/          simulator.py (entrypoint), generators.py, faults.py, instances.py, topology.py
influxdb-mcp/       FastMCP: write_point, query, list_measurements
audit-mcp/          FastMCP: list_incidents, get_session_summary, query_history, query_by_equipment
control-mcp/        FastMCP: propose_action (intercepted), set_setpoint, clear_fault
memory-mcp/         FastMCP: LadybugDB graph + DuckDB analytical queries
topology-builder/   FastMCP: MQTT/OPC-UA discovery, inference, LadybugDB seeding
mqtt-influx-bridge/ Paho subscriber → batched InfluxDB writes
chat-ui/            backend.py, claude_loop.py, multi_agent_loop.py, openai_loop.py,
                    mcp_client.py, session_store.py, control.py, metrics.py, audit.py,
                    providers.json, static/ (index.html + app.js — no framework, no bundler)
mcp-servers/        git submodule → mqtt-mcp, opcua-mcp, strava-mcp, intervals-mcp, analytics-mcp
mcp-aggregator/     git submodule (server/) + backends.json
topology.yaml       single source of truth: process units, fault modes, specialist scopes, alarm limits
data/               gitignored — ladybugdb/, duckdb/, specialist-memory/
```

## Key architecture decisions

**Don't relitigate these:**

- **paho-mqtt over aiomqtt**: `loop_start()` background thread is correct for a publisher. aiomqtt adds a layer with no benefit here.
- **MCP submodules**: never copy files from `mcp-servers/` or `mcp-aggregator/`. Update with `git submodule update --remote`.
- **topology.yaml is the source of truth** for simulator instances, fault modes, specialist scope, and alarm limits. Edit this file; all layers derive from it. `simulator/topology.py` and `chat-ui/topology.py` are duplicate loaders pointing at the same file — known tech debt, don't add a third copy.
- **OPC-UA excluded from specialists**: MQTT and OPC-UA expose the same data; specialists use MQTT only.
- **Named Docker volumes**: data survives `docker compose down`. Wipe with `docker compose down -v`.
- **Fault injection is per-instance** at runtime: `POST /fault?target=RawWater_01&mode=suction_starvation`; clear with `mode=normal`.
- **Setpoints**: `POST /setpoint` on `:8090` alongside `/fault`.
- **Tool result truncation**: results capped at 8,000 chars in conversation history to prevent InfluxDB payload explosion.
- **Current fault status is NOT injected into the system prompt** — the AI must discover faults through tool calls. This is intentional for demo quality.

## Multi-agent architecture

Single aggregator at :8100. Tool isolation enforced by filtering the tool list in Python before each specialist API call — not separate aggregator instances.

| Specialist | Model | Units | Tools |
|---|---|---|---|
| Intake | Haiku | RawWater_01/02 | mqtt + influxdb |
| Treatment | Haiku | Clarifier_01, UV_01/02, Chlorine_01, Fluoride_01 | mqtt + influxdb |
| Distribution | Haiku | HighService_01/02, FinishedWater_01 | mqtt + influxdb |
| Historian | Haiku | (all, historical) | influxdb + memory (DuckDB) |
| Cascade (orchestrator) | Sonnet | — | no tools |

Specialists run in parallel via `asyncio.gather()`. Always fan out to all 4 — no orchestrator dispatch step. Multi-agent mode is disabled until LadybugDB has a committed topology.

## FINDINGS block

Every specialist ends with exactly:
```
FINDINGS:
Status: Normal | Anomaly Detected | Fault Detected
Confidence: 0.0–1.0
Key observations:
- ...
```
If the block is missing, `multi_agent_loop.py` makes a cheap follow-up call with assistant prefill `"FINDINGS:\nStatus:"` to force it. Do not remove this fallback.

## Approval flow (control-mcp)

1. AI calls `propose_action(...)` → backend intercepts
2. Backend streams `action_proposed` SSE to frontend
3. Frontend shows approval dialog
4. Approve → backend calls execution tool → logs to `action_events`
5. Deny → backend injects "operator denied: [action]" back to AI → AI responds → logs denial

Denial path has parity with approval path in `action_events`. `propose_action` only works in single-agent mode — orchestrator has no tools.

## Audit log

`chat-ui/audit.jsonl` — AES-256-GCM per record + SHA-256 hash chain. Set `AUDIT_KEY` env var (base64 32 bytes). Plaintext fallback if unset. Rotate with `rotate_log()` (never `clear_log()`). Verify with `python audit_verify.py`.

## Testing

```bash
pytest tests/
```

Key fixtures in `tests/conftest.py`: fresh LadybugDB from `schema.cypher` via `tmp_path`, seeded simulator, DuckDB connection. MCP tool functions called directly — no SSE transport. Agent loop tests (full Claude API round-trips) are a separate slow suite; don't run with unit suite.

Topology-builder tests:
```bash
pytest topology-builder/tests/
```

## Phase status

Phases 0–11 complete. Phase 11 added ISA-18.2 three-tier reactive alarms: `monitor.py`, `deadband.py`, `reactive_loop.py` in `chat-ui/`. Severity defined in `topology.yaml` per attribute+direction. Opt-in via `REACTIVE_ENABLED=1`.

## What not to touch

- `simulator/simulator.py` main loop — stable, don't refactor without a reason
- `mcp-aggregator/server/` and `mcp-servers/` — these are submodules; changes belong upstream
- `backends.json` lives in `mcp-aggregator/` (not the submodule `server/` directory)
