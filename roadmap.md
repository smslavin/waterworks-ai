# waterworks-ai — Roadmap

Open source industrial AI demonstration stack: natural language process diagnostics
for a simulated water treatment plant, using only open source components and public
protocols.

## Architecture

```
Browser Chat UI
    │
    ▼
Claude API or Ollama
    │
    ▼
MCP Aggregator  (:8100)
    ├── mqtt-mcp     (:8001) ─── Mosquitto MQTT broker
    ├── opcua-mcp    (:8002) ─── OPC-UA server (embedded in simulator)
    └── influxdb-mcp (:8003) ─── InfluxDB
              │
              └─── Simulator ──── publishes to Mosquitto + OPC-UA simultaneously
                                  InfluxDB ◄── AI_Metrics (written by chat backend)
                                  Grafana  ──── optional dashboard
```

## Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Simulator | Python + asyncua + paho-mqtt | asyncio event loop; paho loop_start() for MQTT publish |
| MQTT broker | Mosquitto (Docker) | |
| OPC-UA | asyncua server | Embedded in simulator |
| Time series | InfluxDB 2.x (Docker) | Process data + AI_Metrics |
| Dashboards | Grafana (Docker) | Optional; pre-configured datasource |
| MCP framework | FastMCP | All three MCP servers |
| MCP aggregator | mcp-aggregator (submodule) | Proxies all backends from :8100 |
| Chat backend | Starlette + SSE | Claude API or Ollama, model dropdown |
| LLM | Claude API or Ollama | Switchable per-turn via UI dropdown |

## Repo Structure

```
waterworks-ai/
├── simulator/
│   ├── simulator.py          # Main entrypoint: asyncio, dual MQTT+OPC-UA
│   ├── generators.py         # RandomWalk, OscillatingBool
│   ├── faults.py             # FaultMode enum + value transformation layer
│   ├── instances.py          # WTP instance registry
│   └── requirements.txt
├── influxdb-mcp/
│   ├── server.py             # FastMCP: write_point, query, list_measurements
│   └── requirements.txt
├── chat-ui/
│   ├── backend.py            # Starlette/SSE; Claude API or Ollama routing
│   ├── claude_loop.py        # Claude API streaming loop
│   ├── openai_loop.py        # OpenAI-compatible loop (Ollama)
│   ├── providers.json        # LLM provider + model config
│   ├── metrics.py            # AI_Metrics writer → InfluxDB
│   ├── audit.py              # Per-turn audit log
│   └── static/
│       ├── index.html
│       └── app.js
├── mcp-servers/              # git submodule (mqtt-mcp, opcua-mcp)
├── mcp-aggregator/           # git submodule
│   └── backends.json         # Updated: mqtt, opcua, influxdb endpoints
├── docker-compose.yml        # Mosquitto + InfluxDB + Grafana (named volumes)
├── .env.example
└── roadmap.md
```

## Process Units

| Type | Instance | Attributes |
|---|---|---|
| Pump | RawWater_01, RawWater_02 | Flow, Pressure, Power, Running |
| Pump | HighService_01, HighService_02 | Flow, Pressure, Power, Running |
| Tank | Clarifier_01 | Level, Turbidity |
| Tank | FinishedWater_01 | Level, pH, Turbidity |
| Dosing | Chlorine_01, Fluoride_01 | FlowRate, Running, TankLevel |
| UV | UV_01, UV_02 | Intensity, Running, LampHours |

Topic root: `Plant/WTP/<Type>/<Instance>/<Attribute>`  
OPC-UA path: `Objects/Plant/WTP/<Type>/<Instance>/<Attribute>`

## Fault Injection

Faults apply per-instance at runtime. Toggle via HTTP:

```
POST /fault?target=RawWater_01&mode=suction_starvation
POST /fault?target=RawWater_01&mode=normal
```

| Mode | Description |
|---|---|
| `normal` | Clean random-walk signals |
| `suction_starvation` | Flow ramps to zero, power drops, pressure erratic. Running stays True. |
| `run_status_fault` | Running reads True but Flow ≈ 0 and Power ≈ 0 (stuck feedback bit). |
| `pressure_drift` | Reported pressure diverges from true value via cumulative offset + noise. |
| `cavitation` | Flow collapses with high-frequency noise; pressure spikes and dips rapidly. |

**v2 (future):** Process-wide fault mode — apply a fault to all running pumps simultaneously.

## InfluxDB MCP Tools

| Tool | Purpose |
|---|---|
| `write_point(bucket, measurement, tags, fields)` | Write a tagged data point |
| `query(bucket, flux_query)` | Run arbitrary Flux query; returns formatted text |
| `list_measurements(bucket)` | Discover what measurements exist in a bucket |

AI_Metrics are written directly by the chat backend (not via MCP) using `write_point`
with measurement `ai_metrics` and tags `model`, `session_id`.

## Build Phases

- [x] **Phase 0** — Repo scaffold, roadmap, submodule references
- [x] **Phase 1** — Simulator: `simulator.py`, `generators.py`, `faults.py`, `instances.py`
- [x] **Phase 2** — Infrastructure: `docker-compose.yml` (Mosquitto + InfluxDB + Grafana)
- [x] **Phase 3** — `influxdb-mcp/server.py`
- [x] **Phase 4** — Chat UI: `backend.py`, loops, `providers.json`, `static/`
- [x] **Phase 5** — Wire-up: submodules, `backends.json`, `.env.example`, end-to-end smoke test

## Key Decisions

- **paho-mqtt over aiomqtt**: aiomqtt wraps paho with no benefit for a publisher; paho `loop_start()` is thread-safe alongside asyncio.
- **Per-instance faults**: fault state is per-instance, not process-wide. v2 will add process-wide mode.
- **Three InfluxDB MCP tools**: `write_point`, `query`, `list_measurements` — enough for the AI to do anything without over-engineering the server.
- **Named Docker volumes**: data survives `docker compose down`; wipe with `docker compose down -v`.
- **Git submodules**: mcp-servers and mcp-aggregator are submodules, not copies. Update with `git submodule update --remote`.
