# Architecture overview

This is the 30,000-ft map of waterworks-ai: what each service does and how a
question travels from the operator to the plant and back. For *why* specific
decisions were made, see [`CLAUDE.md`](../CLAUDE.md#key-architecture-decisions)
— this document explains the shape of the system, CLAUDE.md explains the
reasoning behind the shape. For setup/run instructions and demo scripts, see
[`README.md`](../README.md).

waterworks-ai is the reference implementation of the
[Fieldworks](https://github.com/fieldworks-build) framework: an AI operator
for a simulated water treatment plant, built entirely on open protocols
(MQTT, OPC-UA) and open source components. Framework logic (topology
loading, specialist/orchestrator prompts, graph/analytical/memory clients)
lives in the `fieldworks-core` PyPI package; this repo is topology
config, thin MCP server wrappers, the chat-ui backend, and the frontend.

## Service map

```
┌─────────────────────────────────────────────────────────────────────┐
│ Physical layer                                                       │
│   simulator/  — simulated pumps/tanks/clarifiers, publishes over     │
│                 MQTT + OPC-UA, injects faults via HTTP (:8090)       │
└──────────────────┬───────────────────────────────┬──────────────────┘
                    │ MQTT (:1883)                  │ OPC-UA (:4840)
                    ▼                               ▼
┌───────────────────────────────┐   ┌────────────────────────────────┐
│ mqtt-influx-bridge             │   │ mqtt-mcp / opcua-mcp            │
│  Paho subscriber → batched     │   │  Rust fieldworks-adapters,      │
│  InfluxDB writes               │   │  spawned stdio by the           │
└──────────────┬─────────────────┘   │  aggregator (not vendored here) │
               ▼                     └───────────────┬─────────────────┘
┌───────────────────────────────┐                    │
│ InfluxDB (:8086) + Grafana     │                    │
└──────────────┬─────────────────┘                    │
               │                                       │
               ▼                                       ▼
        ┌──────────────────────────────────────────────────┐
        │ influxdb-mcp (:8003)      mcp-aggregator (:8100)   │
        │ audit-mcp (:8004)         — single MCP tool        │
        │ control-mcp (:8005)         gateway every caller    │
        │ memory-mcp (:8006)          talks to, backed by     │
        │ topology-builder (:8007)    backends.json           │
        └───────────────────────┬────────────────────────────┘
                                 │ MCP tools (mqtt__*, influxdb__*,
                                 │ control__*, audit__*, memory__*)
                                 ▼
        ┌────────────────────────────────────────────────────┐
        │ chat-ui backend (:8080)                              │
        │  claude_loop.py       single-agent diagnostic loop   │
        │  multi_agent_loop.py  specialist fan-out + Cascade   │
        │  reactive_loop.py     MQTT-driven background watch   │
        │  status_heartbeat.py  periodic per-plant status roll-up │
        │  control.py / audit.py   approval flow + encrypted log │
        └───────────────────────┬────────────────────────────┘
                                 │ SSE
                                 ▼
        ┌────────────────────────────────────────────────────┐
        │ chat-ui/frontend (Vue 3 + Pinia)                     │
        └────────────────────────────────────────────────────┘
```

Everything above is per-plant — an M10 multi-plant deployment runs a full
second copy of this stack with its own `.env`. The **enterprise layer**
(`enterprise/`) sits above every plant and never touches a plant's
aggregator, MQTT, or InfluxDB directly:

```
enterprise/orchestrator (:8020)  — Cascade-shaped loop, tools are
                                    diagnose_plant + get_plant_status only
        │
        ▼
enterprise/diagnose_plant_mcp (:8200)  — thin HTTP proxy: forwards to each
                                          plant's own chat-ui /api/chat and
                                          /api/plant-status. Holds no
                                          cross-plant credentials.
        │
        ▼
each plant's chat-ui (per plant_registry.py → enterprise.yaml)
```

## Request lifecycle: a diagnostic question

1. **Operator asks a question** in the chat-ui frontend. The frontend opens
   an SSE stream to `chat-ui/backend.py`.
2. **Mode selection.** Single-agent mode runs `claude_loop.py` — one Claude
   instance with the full MQTT/InfluxDB/control/audit/memory tool list.
   Multi-agent mode (`multi_agent_loop.py`) fans out to 4 parallel Haiku
   specialists (Intake, Treatment, Distribution, Historian), each scoped to
   its own process-area tools by prefix filtering — not separate aggregator
   instances or processes.
3. **Specialists call MCP tools** through `mcp_client.py`, which always
   talks to the single `mcp-aggregator` (:8100). The aggregator is the only
   thing that knows how each backend in `backends.json` is actually reached
   (stdio subprocess for `mqtt`/`opcua`, SSE URL for everything else).
4. **Each specialist ends with a `FINDINGS:` block** (status, confidence,
   observations). If the model doesn't produce one — either it ends its
   turn without one, or it hits `SPECIALIST_MAX_ROUNDS` (4) of tool calls
   first — `_ensure_findings()` forces a cheap follow-up call to extract it.
   This is what keeps one slow specialist from stalling the whole plant's
   answer indefinitely.
5. **Cascade (Sonnet) synthesizes** the specialist findings into one answer,
   leading with a `SUMMARY:` block. Cascade has its own tools:
   `control__*` and `audit__*` — the only agent in the system that can
   propose a control action or query the audit trail.
6. **If Cascade proposes a control action** (`control__propose_action`), the
   backend intercepts the call before it reaches the aggregator, streams an
   `action_proposed` event to the frontend, and blocks on a `Future`
   (`control.py`) until the operator approves or denies via
   `/api/action/respond`. Both outcomes are logged to `action_events` with
   equal detail — a denial has the same audit shape as an approval.
7. **Every tool call and result** is written to `chat-ui/audit.jsonl`
   (AES-256-GCM + SHA-256 hash chain if `AUDIT_KEY` is set) and to
   `metrics.db` (session summaries, per-turn token/latency metrics,
   per-plant status rollups). `audit-mcp` reads the same `metrics.db` to
   answer `list_incidents`/`query_history`/etc.
8. **Findings that matter beyond one session** are written to
   `memory-mcp`: a diagnosed incident becomes a LadybugDB `Incident` node
   (`memory__record_incident`), and confident findings are appended to
   that specialist's own long-lived memory file
   (`memory__append_specialist_memory`), which gets prepended to that
   specialist's system prompt on its *next* invocation — this is the only
   cross-session learning mechanism; there is no fine-tuning or RL.

## Always-on layers (no operator question required)

- **`monitor.py`** tracks MQTT readings against topology-declared normal
  ranges continuously from chat-ui boot — cheap, no LLM calls, no
  dependency on reactive mode being enabled.
- **`reactive_loop.py`** (opt-in via `REACTIVE_ENABLED`) escalates threshold
  breaches monitor.py detects to a cheap Deadband (Haiku) triage step, which
  can escalate further to a scoped Cascade diagnosis of just the affected
  process area.
- **`status_heartbeat.py`** periodically runs a full but concise multi-agent
  diagnosis and caches the result (`session_store.upsert_plant_status`) so
  enterprise-level "what's the status" questions can read a DB row instead
  of triggering a live diagnosis. It triggers a real check when
  `monitor.py`'s cheap signal changes, or unconditionally every
  `STATUS_HEARTBEAT_MAX_STALE_TICKS` ticks as a backstop — `monitor.py` only
  sees numeric excursions, not discrete equipment state, so it can't be
  trusted alone to decide "nothing changed."

## Topology as source of truth

`topology.yaml` (fieldworks-core spec schema) declares process areas,
equipment instances, fault modes, alarm limits, and specialist scope. It is
loaded once via `fieldworks.topology.load()` and drives: which specialists
exist and what units they own (`multi_agent_loop._build_specialists`),
simulator generation ranges (paired with `simulator.yaml` for
simulator-only mechanics), and topology-builder's LadybugDB seeding.
`topology-builder/` exists to *build* a topology.yaml from live MQTT/OPC-UA
discovery for a real (non-simulated) plant — its crawler
(`discovery.py`) talks to MQTT/OPC-UA directly rather than through the
aggregator, since discovery has to work before any topology-derived tool
scoping exists.

## Where the framework ends and this repo begins

Anything that would need to change to diagnose a *different* plant with a
*different* topology.yaml is framework code and lives in `fieldworks-core`,
not here (see the note at the top of `CLAUDE.md`). What's left in this repo
is: `topology.yaml`/`simulator.yaml` as this plant's specific configuration,
MCP server wrappers that expose that plant's tools, the Starlette backend
that orchestrates a conversation, and the Vue 3 frontend. When adding a
feature, that's the question worth asking first: does this belong to *any*
Fieldworks plant, or specifically to this one?
