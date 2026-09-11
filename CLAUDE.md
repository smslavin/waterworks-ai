# waterworks-ai

Open source industrial AI demo stack: natural language diagnostics for a simulated water treatment plant using only open source components and public protocols. Reference implementation of the Fieldworks framework.

For the system-level picture (service map, request lifecycle, always-on layers) see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). This file covers decisions, gotchas, and things not to touch.

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
| query_history_mcp (enterprise, M10) | 8201 |
| Enterprise orchestrator (M10) | 8020 |

M10 multi-plant: every port above except the enterprise layer is per-plant —
a second plant runs a full second checkout with its own `.env` overriding
each one (see `enterprise.yaml`, `plant_registry.py`). The enterprise layer
itself runs once, shared across every plant it's configured to reach.

**M10 Phase 4 — SiteNav wiring**: `chat-ui/backend.py` exposes `GET /api/site`
(this plant's own `SITE_ID`/`SITE_NAME`/`REGION_NAME`) and `GET /api/sites`
(server-side proxy of the enterprise orchestrator's `/api/sites`, so the
orchestrator's URL stays backend config, not a second CORS surface). The
frontend's `SiteNav.vue` uses these to seed `stores/ui.ts`'s `activeSite`/
`activeRegion` and to list real cross-plant sites. **Switching sites is a
full browser navigation** to the target plant's own `chat_ui_url`, not an
in-app API repoint — deliberately, to avoid opening CORS between plant
origins on a system with an actuation path (`control-mcp`'s `set_setpoint`).
Only this plant's own area-status dots in `SiteNav.vue` are real (sourced
from `stores/topology.ts`); other plants show no dots (no live cross-plant
health fetch exists yet). Live in-app switching (the CORS-based version) is
deferred — see smslavin/waterworks-ai#7.

**Fast status path**: `chat-ui/status_heartbeat.py` runs a periodic (default
15 min) background diagnosis and caches the result via
`session_store.upsert_plant_status()`, exposed as `GET /api/plant-status`
and proxied to the enterprise orchestrator as the `get_plant_status(site_id)`
tool in `diagnose_plant_mcp`. The orchestrator defaults to this fast path for
overview/status questions and only reaches for the slow live `diagnose_plant`
path for genuine drill-down — verified live at 28s vs. 1-5+ min for an
"overall status across the enterprise" question. `status_level` is always
parsed from the cached narrative itself, never from `monitor.py`'s cheap
threshold check directly — the threshold check only sees numeric excursions,
not discrete equipment state, and live testing showed it disagree with a real
diagnosis. It's used only as a trigger signal for *when* to pay for a real
check, with `STATUS_HEARTBEAT_MAX_STALE_TICKS` (default 4×15min = 1hr) as a
backstop for what it can't see at all.

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
                    diagnose_plant_mcp/server.py MCPServer: diagnose_plant(site_id, query) +
                                                  get_plant_status(site_id) — thin HTTP client
                                                  of each plant's own chat-ui /api/chat and
                                                  /api/plant-status, no aggregator/MQTT/
                                                  InfluxDB access of its own
                    query_history_mcp/server.py  MCPServer: query_enterprise_history(...) —
                                                  federated read across every plant's own
                                                  audit-mcp (calls each plant's aggregator
                                                  directly; audit data doesn't need
                                                  diagnose_plant_mcp's stricter guarantee)
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
| Cascade (orchestrator) | Sonnet | — | control__* + audit__* |

Specialists run in parallel via `asyncio.gather()`. Always fan out to all 4 — no orchestrator dispatch step. Multi-agent mode is disabled until LadybugDB has a committed topology.

Each specialist is capped at `SPECIALIST_MAX_ROUNDS` (4) tool-calling rounds — an unbounded per-specialist loop was the actual cause behind every "slow"/"timeout" report, since `diagnose_plant`'s 240s per-plant timeout sits on top of 4 parallel specialists with no ceiling of their own. Hitting the cap forces the same `_ensure_findings()` fallback used when a specialist ends its turn without a FINDINGS block.

In multi-agent mode, a specialist's `Fault Detected`/`Anomaly Detected` FINDINGS recolor that unit's node on the topology graph (`chat-ui/frontend/src/stores/topology.ts`) — gated on multi-agent mode only, since single-agent has no per-equipment FINDINGS parsing and the enterprise region-proxy path forwards another plant's specialist ids under the same names.

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
4. Approve → `control.py` stamps a one-time execution grant (session + tool + exact args, hashed) → AI calls the execution tool → backend refuses it unless a matching grant is presented and consumed → logs to `action_events`
5. Deny → backend injects "operator denied: [action]" back to AI → AI responds → logs denial

Approval alone does not execute anything — the grant is what does, and it's bound to the exact target/attribute/value that were proposed; a drifted execution call (rounded value, different target) is refused, not silently coerced. `propose_action` is intercepted in three places, not shared code: single-agent mode (`claude_loop.py`), multi-agent mode's orchestrator loop, and multi-agent mode's follow-up-question path (`multi_agent_loop.py`'s `_run_cascade_only`) — a fix to one (e.g. denial-message wording) does not automatically apply to the others.

## Network exposure

`chat-ui/backend.py` and the simulator's control plane (`:8090`) bind to loopback (`BIND_HOST`, default `127.0.0.1`) — nothing off-host can reach the approval endpoint, control writes, or the audit log by default. Set `BIND_HOST=0.0.0.0` only to deliberately expose the app (e.g. to a phone on the same LAN); doing so requires `WATERWORKS_API_TOKEN` on chat-ui's mutating/audit routes (`chat-ui/auth.py`) — a bearer header or `?token=` query param, checked with `secrets.compare_digest`. Unset, the server generates one at startup and logs it. This is a demo-scope shared-secret gate, not a login system — see `chat-ui/auth.py`'s module docstring before extending it.

## Audit log

`chat-ui/audit.jsonl` — AES-256-GCM per record, HMAC-SHA256 hash chain keyed under `AUDIT_KEY` (base64 32 bytes). Unset is allowed (plaintext, dev mode, logs a WARNING); set-but-invalid (bad base64, wrong length, `cryptography` not installed) raises at import rather than silently falling back to plaintext. `AUDIT_REQUIRE_ENCRYPTION=1` refuses to start without a valid key. The first record of every process is `audit_log_opened` naming the active mode.

Rotate with `rotate_log()` (never `clear_log()`) — the new file's first record carries the archived file's final hash as its `prev`, so the chain spans the rotation; `python audit_verify.py <log> --prev-file <archive>` checks it end to end, or without `--prev-file` for a single file (record 1's non-empty `prev` is itself the tell that this isn't a from-scratch complete log). `verify()` also checks `seq` for gaps, catching a record deleted from the middle even if whoever edited the file forgot to re-chain it — deletions off the *end* of a file aren't detectable this way (nothing references what's missing); that needs an external anchor and is out of scope.

`action_events` (per-action compliance rows in `metrics.db`) has parity between the proposal and every later state: `log_action_proposed()` inserts a `pending`/`pending` row before the operator's answer is awaited (not after, which is what `claude_loop.py`/`multi_agent_loop.py` used to do — a restart mid-approval left the proposal with no record at all), `log_action_decision()` updates it once answered (a denial settles `outcome='not_executed'` immediately), and `log_action_outcome()` records the real execution result (`ok` / `failed: <error>`) once the grant from `control.py` is actually consumed. `session_store.recover_abandoned_actions()` runs at `backend.py` startup and sweeps any row still `pending` from a previous process — its in-memory `control.py` Future is gone and will never resolve. There's no `operator_id` column any more — the old `'operator_01'` constant asserted an identity #15's shared-secret token doesn't actually provide; dropped rather than left hardcoded-wrong.

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


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:6cd5cc61 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->
