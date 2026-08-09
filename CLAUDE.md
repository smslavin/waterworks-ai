# waterworks-ai

Open source industrial AI demo stack: natural language diagnostics for a simulated water treatment plant using only open source components and public protocols. Reference implementation of the Fieldworks framework.

**Depends on fieldworks-core** (PyPI package, version-pinned per-service in each `requirements.txt`) as of the M8 port (v2.0.0): topology loading, specialist/orchestrator/Deadband prompts, LadybugDB/DuckDB/specialist-memory clients, and topology-builder's inference engine all come from the framework now. No framework logic remains in this repo — only topology.yaml/simulator.yaml config, thin MCP server wrappers, the Starlette backend, and the Vue 3 frontend. **MQTT/OPC-UA adapters** (fieldworks-core#14/#21, 2026-07-19): swapped from the old `mcp-servers/` Python submodule to the Rust `fieldworks-adapters` binaries (`mqtt-mcp`, `opcua-mcp`), installed via `cargo install` and spawned by the aggregator itself as stdio subprocesses (see `mcp-aggregator/backends.json`). The `mcp-servers` submodule is gone — nothing in this repo uses it anymore. `topology-builder/discovery.py`'s crawler still bypasses the aggregator entirely — its own direct paho-mqtt/asyncua clients, not MCP tool calls at all — pending fieldworks-core#22.

## Starting the stack

```bash
# 1. Infrastructure (Mosquitto :1883, InfluxDB :8086, Grafana :3000)
docker compose up -d

# 2. Submodules (if not yet initialized)
git submodule update --init --recursive

# 2b. mqtt-mcp/opcua-mcp binaries (if not yet installed) — the aggregator spawns
#     these itself as stdio subprocesses, no separate terminal needed for them:
cargo install --git https://github.com/fieldworks-build/fieldworks-adapters mqtt-mcp opcua-mcp

# 3. Each service — run in separate terminals from its directory with uv:
cd simulator         && uv run python simulator.py
cd mqtt-influx-bridge && uv run python bridge.py
cd influxdb-mcp      && uv run python server.py
cd audit-mcp         && uv run python server.py
cd control-mcp       && uv run python server.py
cd memory-mcp        && uv run python server.py
cd topology-builder  && uv run python server.py
cd mcp-aggregator/server && uv run python server.py
cd chat-ui           && uv run python backend.py
```

Chat UI: http://localhost:8080  
Dashboard overview: open `dashboard.html` in browser.

## Port map

| Service | Port |
|---|---|
| Chat UI | 8080 |
| mqtt-mcp / opcua-mcp | none — stdio, spawned by the aggregator |
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
| diagnose_plant_mcp (enterprise, M10) | 8200 |
| Enterprise orchestrator (M10) | 8020 |

M10 multi-plant: every port above except the enterprise layer is per-plant —
a second plant runs a full second checkout with its own `.env` overriding
each one (see `enterprise.yaml`, `plant_registry.py`). The enterprise layer
itself runs once, shared across every plant it's configured to reach.

## Repo structure

```
simulator/          simulator.py (entrypoint), generators.py, faults.py, instances.py, topology.py
influxdb-mcp/       MCPServer: write_point, query, list_measurements
audit-mcp/          MCPServer: list_incidents, get_session_summary, query_history, query_by_equipment
control-mcp/        MCPServer: propose_action (intercepted), set_setpoint, clear_fault
memory-mcp/         MCPServer: LadybugDB graph + DuckDB analytical/knowledge (RAG) queries
topology-builder/   MCPServer: MQTT/OPC-UA discovery, inference, LadybugDB seeding
mqtt-influx-bridge/ Paho subscriber → batched InfluxDB writes
chat-ui/            backend.py, claude_loop.py, multi_agent_loop.py, openai_loop.py,
                    mcp_client.py, session_store.py, control.py, metrics.py, audit.py,
                    providers.json, static/ (Vite build output — do not edit directly),
                    frontend/ (Vue 3 + Vite source — edit here, then npm run build)
mcp-aggregator/     git submodule (server/) + backends.json
                    mqtt/opcua entries are stdio — aggregator spawns the fieldworks-adapters
                    mqtt-mcp/opcua-mcp binaries itself (cargo-installed, not vendored here)
topology.yaml       single source of truth: process units, fault modes, specialist scopes, alarm limits
enterprise.yaml     M10: regions -> sites (site_id, topology_file, chat_ui_url) — read by
                    enterprise/plant_registry.py, not by any single plant's own process
enterprise/         M10 multi-plant layer — shared across every plant, not per-checkout:
                    plant_registry.py            site_id -> chat_ui_url lookup
                    diagnose_plant_mcp/server.py MCPServer: diagnose_plant(site_id, query) —
                                                  thin HTTP client of each plant's own
                                                  chat-ui /api/chat, no aggregator/MQTT/
                                                  InfluxDB access of its own
                    orchestrator/                Starlette app + Cascade-shaped loop whose
                                                  only tool is diagnose_plant
                    start.sh/stop.sh/restart.sh  separate from each plant checkout's own —
                                                  run once, not per plant
data/               ladybugdb/, duckdb/, specialist-memory/ are gitignored (generated
                    state); knowledge-docs/ is committed source content — facility
                    docs ingested by memory-mcp's KnowledgeClient
```

## Key architecture decisions

**Don't relitigate these:**

- **paho-mqtt over aiomqtt**: `loop_start()` background thread is correct for a publisher. aiomqtt adds a layer with no benefit here.
- **MCP submodules**: never copy files from `mcp-aggregator/`. Update with `git submodule update --remote`.
- **mqtt-mcp/opcua-mcp connection**: the Rust adapters don't auto-connect at startup like the old Python ones did — `connect` is an explicit MCP tool call. `chat-ui/backend.py`'s `lifespan` fires `mqtt__connect` once in the background on startup (bounded retry, absorbs the aggregator/mosquitto startup race). `opcua__connect` is not called anywhere — nothing currently calls `opcua__*` tools (specialists are MQTT-only; see below).
- **topology.yaml is the source of truth** for equipment, fault modes, and specialist scope — in the fieldworks-core spec schema (list-based, explicit tag_bindings) since the M8 port. `simulator/topology.py` and `chat-ui/topology.py` are thin shims re-exporting the root `topology.py`, which delegates to `fieldworks.topology.load()`. Simulator-only generation mechanics (lo/hi/step/initial/flip, per-instance overrides) live in `simulator.yaml` instead — topology.yaml stays a clean, spec-compliant worked example (it's cited directly in the framework spec).
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

Topology-builder's inference tests live in fieldworks-core (M6), not in this repo — `topology-builder/tests/` was removed in the M8 port (a777299).

## Frontend development

The Vue 3 frontend lives in `chat-ui/frontend/`. The backend serves the built output from `chat-ui/static/`.

```bash
# Build for production (run from chat-ui/frontend/):
npm run build        # outputs to ../static; backend picks it up immediately

# Dev server with hot-reload (proxies /api/* to backend on :8080):
npm run dev          # http://localhost:5173

# Tests:
npm run test:unit    # Vitest (166 tests)
npm run type-check   # vue-tsc
```

Do not edit files in `chat-ui/static/` directly — they are overwritten on every build.

## Phase status

Phases 0–13 complete. Phase 12 replaced the vanilla HTML/JS frontend with a Vue 3 + Vite + Pinia app (topology graph, streaming panels, reactive alarms, multi-agent mode, approval flow). Phase 13: insight categories.

**M8 — fieldworks-core port (v2.0.0):** rebuilt as the framework's reference implementation. topology.yaml migrated to the fieldworks-core spec schema; chat-ui/simulator/memory-mcp/topology-builder now depend on fieldworks-core instead of containing their own copies of that logic. See the note at the top of this file.

**M9 / Phase 14 — knowledge memory / RAG (fieldworks-core v1.1.0):** `memory-mcp` now wraps `fieldworks.memory.KnowledgeClient` (DuckDB + VSS, local `fastembed` embeddings by default) alongside the existing graph/analytical clients. Facility docs (`.md`/`.txt`/`.pdf`) dropped into `data/knowledge-docs/` are ingested on every `memory-mcp` boot (content-hash change detection skips unchanged files) and exposed via the `memory__query_knowledge` tool, available to every specialist. Example docs (`pump-operating-limits.md`, `clarifier-uv-manual-excerpt.md`) ship in the repo so the demo has something to retrieve out of the box.

## What not to touch

- `simulator/simulator.py` main loop — stable, don't refactor without a reason
- `mcp-aggregator/server/` — this is a submodule; changes belong upstream
- `backends.json` lives in `mcp-aggregator/` (not the submodule `server/` directory)

## Smoke-testing services touches real data by default — redirect paths first

`memory-mcp/server.py` (and any script importing it) defaults its DB paths to
real repo state: `LADYBUG_DB_PATH`, `DUCKDB_PATH`, `KNOWLEDGE_DUCKDB_PATH`,
`SPECIALIST_MEMORY_DIR`, `KNOWLEDGE_DOCS_DIR` all resolve to `../data/...`
relative to `memory-mcp/` — i.e. the actual `waterworks-ai/data/` directory,
not a throwaway path. Importing `server` module-level, or calling
`_maybe_seed_from_topology()` / `_maybe_ingest_knowledge_docs()` /
`AnalyticalClient.sync_loop()` directly, writes into that real data the
moment the module loads or the lifespan runs — there is no dry-run mode.

Before running `server.py` or importing it for any ad-hoc check, override
every path env var to a scratch directory first (e.g. `LADYBUG_DB_PATH`,
`DUCKDB_PATH`, `KNOWLEDGE_DUCKDB_PATH` set to paths under `/tmp` or a
scratchpad). Never `rm -rf` anything under `data/` as "cleanup" without
first confirming the paths involved are ones you pointed at yourself — the
static LadybugDB layer and the DuckDB analytical cache both self-heal
(reseed from `topology.yaml`, resync from InfluxDB), but LadybugDB's
*dynamic* layer — recorded `Incident`/`Observation`/`OperatorDecision` nodes
from real sessions — has no other source and does not come back.
