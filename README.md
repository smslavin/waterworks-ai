<img src="chat-ui/static/icon-light.png" alt="Waterworks AI" width="80">

# waterworks-ai

Open source demonstration of natural language industrial process diagnostics. A simulated water treatment plant publishes live sensor data over MQTT and OPC-UA; an AI assistant reads that data through MCP tool calls and diagnoses process conditions in plain English.

Everything in this stack is open source. No proprietary historians, SCADA platforms, or cloud connectors required.

---

## How it works

```
Browser Chat UI
    │
    ▼
Claude API or Ollama
    │
    ▼
MCP Aggregator  :8100
    ├── mqtt-mcp      :8001 ──► Mosquitto MQTT broker  :1883
    ├── opcua-mcp     :8002 ──► OPC-UA server (in simulator)
    └── influxdb-mcp  :8003 ──► InfluxDB  :8086
                                    ▲
Simulator ──────────────────────────┤  publishes to MQTT + OPC-UA simultaneously
                                    │
MQTT → InfluxDB bridge ─────────────┘  subscribes Plant/WTP/# → writes wtp_process
  Chat backend also writes AI_Metrics to InfluxDB per turn
```

The simulator runs a configurable fault injection engine. Inject a fault mid-session and ask the AI to diagnose it — it reads live values, correlates anomalies across instruments, and explains what it sees.

---

## Prerequisites

- **Docker Desktop** — runs Mosquitto, InfluxDB, and Grafana
- **Python 3.11+** — all components are pure Python
- **[uv](https://docs.astral.sh/uv/)** — fast Python package manager (`brew install uv` or `pip install uv`)
- **Anthropic API key** — or a local [Ollama](https://ollama.com) installation

---

## Quick start

```bash
git clone --recurse-submodules https://github.com/smslavin/waterworks-ai
cd waterworks-ai
cp .env.example .env
# edit .env: set ANTHROPIC_API_KEY
```

Each component gets its own virtualenv. Run this once to create and populate all of them:

```bash
(cd simulator              && uv venv && uv pip install -r requirements.txt)
(cd mcp-servers/mqtt-mcp  && uv venv && uv pip install -r requirements.txt)
(cd mcp-servers/opcua-mcp && uv venv && uv pip install -r requirements.txt)
(cd influxdb-mcp           && uv venv && uv pip install -r requirements.txt)
(cd mcp-aggregator/server  && uv venv && uv pip install -r requirements.txt)
(cd chat-ui                && uv venv && uv pip install -r requirements.txt)
(cd mqtt-influx-bridge     && uv venv && uv pip install -r requirements.txt)
```

Then open six terminals (or a terminal multiplexer) and run each in order:

```bash
# 1 — Infrastructure
docker compose up -d

# 2 — Simulator  (MQTT + OPC-UA, fault control on :8090)
cd simulator && .venv/bin/python simulator.py

# 3 — MQTT MCP server
cd mcp-servers/mqtt-mcp && FASTMCP_PORT=8001 .venv/bin/python server.py

# 4 — OPC-UA MCP server
cd mcp-servers/opcua-mcp && FASTMCP_PORT=8002 .venv/bin/python server.py

# 5 — InfluxDB MCP server
cd influxdb-mcp && .venv/bin/python server.py

# 6 — MCP Aggregator  (our backends.json, upstream server code)
cd mcp-aggregator/server && BACKENDS_FILE=../backends.json .venv/bin/python server.py

# 7 — MQTT → InfluxDB bridge  (writes process data to InfluxDB for historical queries)
cd mqtt-influx-bridge && .venv/bin/python bridge.py

# 8 — Chat UI
cd chat-ui && .venv/bin/python backend.py
```

Open **http://localhost:8080** in a browser.

---

## Process units

The simulator models a municipal water treatment plant.

| Type | Instance | Attributes |
|---|---|---|
| Pump | RawWater_01, RawWater_02 | Flow (L/min), Pressure (bar), Power (kW), Running |
| Pump | HighService_01, HighService_02 | Flow (L/min), Pressure (bar), Power (kW), Running |
| Tank | Clarifier_01 | Level (%), Turbidity (NTU) |
| Tank | FinishedWater_01 | Level (%), pH, Turbidity (NTU) |
| Dosing | Chlorine_01, Fluoride_01 | FlowRate (L/h), Running, TankLevel (%) |
| UV | UV_01, UV_02 | Intensity (%), Running, LampHours |

MQTT topic pattern: `Plant/WTP/<Type>/<Instance>/<Attribute>`  
OPC-UA path pattern: `Objects/Plant/WTP/<Type>/<Instance>/<Attribute>`

---

## Fault injection

Faults are applied per-instance at runtime without restarting the simulator. The chat UI has an injection panel in the input area. You can also use the HTTP control plane directly:

```bash
# Inject a fault
curl -X POST "http://localhost:8090/fault?target=RawWater_01&mode=suction_starvation"

# Clear it
curl -X POST "http://localhost:8090/fault?target=RawWater_01&mode=normal"

# Check all instances
curl http://localhost:8090/status
```

| Mode | What it simulates |
|---|---|
| `suction_starvation` | Supply cut to a running pump. Flow ramps toward zero over ~50 s; pressure becomes erratic. Running stays True. |
| `run_status_fault` | Feedback bit stuck True while pump is actually off. Flow and Power read near zero. |
| `pressure_drift` | Transmitter calibration drift. Reported pressure diverges progressively from true value. |
| `cavitation` | Intermittent vapor formation. Flow collapses unpredictably; pressure spikes and dips rapidly. |

A good demo sequence: start a conversation, inject a fault on RawWater_01, then ask *"Is anything wrong with the raw water intake?"*

---

## Dashboards

Grafana is available at **http://localhost:3000** (admin / waterworks by default). The InfluxDB datasource is pre-provisioned. AI_Metrics are written to the `ai_metrics` measurement with `model` and `session_id` tags — fields include `input_tokens`, `output_tokens`, `tool_call_count`, `latency_ms`.

InfluxDB UI is at **http://localhost:8086**.

---

## Configuration

All configuration lives in `.env`. Copy `.env.example` to get started — the defaults work for a local run without changes except for `ANTHROPIC_API_KEY`.

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | _(empty)_ | Required for Claude models |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama base URL |
| `INFLUXDB_TOKEN` | `waterworks-dev-token` | Set once at first `docker compose up` |
| `INFLUXDB_ORG` | `waterworks` | InfluxDB organisation |
| `INFLUXDB_BUCKET` | `waterworks` | Default bucket for all data |
| `PUBLISH_INTERVAL` | `2.0` | Simulator tick rate in seconds |
| `OPCUA_PORT` | `4840` | OPC-UA server port |
| `CONTROL_PORT` | `8090` | Simulator fault control HTTP port |

> **Note:** `INFLUXDB_TOKEN` and the other `DOCKER_INFLUXDB_INIT_*` values are only used on a fresh volume. After the first `docker compose up` they are baked in. Reset with `docker compose down -v`.

---

## Project layout

```
waterworks-ai/
├── simulator/              Dual MQTT+OPC-UA WTP simulator with fault injection
│   ├── simulator.py        Entrypoint — asyncio event loop, paho MQTT, asyncua
│   ├── generators.py       RandomWalk and OscillatingBool value generators
│   ├── faults.py           FaultMode enum and per-instance fault state machine
│   └── instances.py        WTP instance registry
├── influxdb-mcp/           FastMCP server: write_point, query, list_measurements
├── chat-ui/                Starlette/SSE backend and vanilla JS frontend
│   ├── backend.py          Routes: /api/chat, /api/models, /api/health, /api/fault
│   ├── claude_loop.py      Claude API streaming loop with MCP tool calling
│   ├── openai_loop.py      OpenAI-compatible loop for Ollama
│   ├── mcp_client.py       MCP aggregator client (list tools, call tools)
│   ├── metrics.py          AI_Metrics → InfluxDB per turn
│   ├── audit.py            JSONL audit log
│   ├── providers.json      LLM provider and model configuration
│   └── static/             index.html + app.js (no framework, no bundler)
├── mqtt-influx-bridge/     Subscribes Plant/WTP/# → writes wtp_process to InfluxDB
│   └── bridge.py           Paho subscriber + batched InfluxDB write
├── mcp-servers/            Git submodule — mqtt-mcp (:8001) and opcua-mcp (:8002)
├── mcp-aggregator/
│   ├── server/             Git submodule — aggregator server code (:8100)
│   └── backends.json       Waterworks endpoint config (BACKENDS_FILE=../backends.json)
├── docker/
│   ├── mosquitto/          mosquitto.conf (anonymous, persistence on)
│   └── grafana/            Provisioned InfluxDB datasource
├── docker-compose.yml      Mosquitto + InfluxDB 2.7 + Grafana (named volumes)
└── .env.example            All environment variables with defaults
```

---

## Extending

**Add a new process unit:** edit `simulator/instances.py` — add an entry to `INSTANCES`. It appears in both MQTT and OPC-UA automatically.

**Add a new fault mode:** add a member to `FaultMode` in `simulator/faults.py` and a corresponding `_method` in `FaultState`. The HTTP control plane picks it up with no other changes.

**Add an MCP server:** add an entry to `mcp-aggregator/backends.json`. The aggregator discovers and prefixes its tools at startup.

**Add a Grafana dashboard:** drop a JSON dashboard file into `docker/grafana/provisioning/dashboards/` and add a dashboards provisioning YAML alongside it.
