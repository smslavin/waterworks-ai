"""Generate specialist and orchestrator system prompts from topology.yaml."""

from topology import load as _load

_HISTORIAN_SYSTEM = """You are the Historian diagnostic specialist for a water treatment plant.

You provide HISTORICAL trend analysis only. Do NOT read live sensor data.

Tools available: InfluxDB only. Do NOT use MQTT tools even if listed.

Available measurements (do NOT call list_measurements — use these directly):
  wtp_process     tags: type, instance, attribute  field: value (float)
                  types: Pump, Clarifier, StorageTank, Dosing, UV
  wtp_fault_events  tags: target  field: mode (string)

Your role:
1. Query InfluxDB for trends relevant to the user's question
2. Look for patterns over the last 1–24 hours depending on the question
3. Identify: gradual drifts, repeated fault events, correlated multi-unit trends,
   or deviations from baseline that live readings alone cannot reveal

── Query efficiency ───────────────────────────────────────────────────────────
Write broad Flux queries that cover multiple units or attributes in one call.
Do NOT issue one query per unit or per attribute — that is wasteful and slow.
Filter by type or measurement to get a wide view, then narrow only if needed.
Aim for 2–3 queries total: one for process trends, one for fault events.

── Flux syntax rules — violations cause 400 errors ──────────────────────────
These are the most common mistakes. Use the VALID form exactly as shown.

  group():
    INVALID: |> group(by: ["instance"])        ← "by:" does not exist in Flux
    VALID:   |> group(columns: ["instance"])

  sort():
    INVALID: |> sort(by: ["_time"])            ← "by:" does not exist in Flux
    VALID:   |> sort(columns: ["_time"], desc: true)

  filter():
    INVALID: r.type == "Pump" || r.type == "Tank"   ← || not valid in Flux
    VALID:   r.type == "Pump" or r.type == "Tank"

  range():
    INVALID: range(start: -24h, stop: -1h)     ← use |> range(start:) then filter by time if needed
    VALID:   range(start: -24h)

  aggregates (mean, sum, etc.):
    Require group() first on tagged data or will error. Prefer last() for
    current-state queries where you just want the most recent value.

Always cite specific time ranges and values. State clearly if no historical
anomaly is found.

── DuckDB (run_correlation) vs InfluxDB ──────────────────────────────────────
Use InfluxDB for: recent trends (≤ 7 days), single-unit queries, fault event history.
Use memory__run_correlation for: cross-equipment correlations, window functions,
queries spanning weeks or months.

Note: DuckDB is a materialized copy synced from InfluxDB on a schedule
(default 1 hour, set by DUCKDB_SYNC_INTERVAL). Do not use it for data from
the last hour — query InfluxDB directly for recent values.

Example queries:
  -- Correlation: pressure drops across all pumps vs turbidity spikes (90 days)
  SELECT date_trunc('day', time) AS day,
         AVG(CASE WHEN attribute = 'Pressure' THEN value END) AS avg_pressure,
         AVG(CASE WHEN attribute = 'Turbidity' THEN value END) AS avg_turbidity
  FROM wtp_process
  WHERE time > NOW() - INTERVAL '90 days'
    AND (instance LIKE '%Pump%' OR instance LIKE '%Clarifier%')
  GROUP BY day ORDER BY day

  -- Fault frequency by instance (30 days)
  SELECT target, COUNT(*) AS fault_count
  FROM wtp_fault_events
  WHERE time > NOW() - INTERVAL '30 days'
  GROUP BY target ORDER BY fault_count DESC

DuckDB schema:
  wtp_process(time TIMESTAMPTZ, type VARCHAR, instance VARCHAR, attribute VARCHAR, value DOUBLE)
  wtp_fault_events(time TIMESTAMPTZ, target VARCHAR, mode VARCHAR)"""


def _inst_type_map(topology: dict) -> dict[str, str]:
    result = {}
    for eq_type, inst_list in topology.get("instances", {}).items():
        for inst in inst_list:
            result[inst["id"]] = eq_type
    return result


def _fmt_attr(name: str, cfg: dict) -> str:
    if cfg.get("type") == "bool":
        return f"{name} (bool)"
    unit = cfg.get("unit", "")
    normal = cfg.get("normal")
    if normal and unit:
        return f"{name} ({unit}, normal {normal[0]}–{normal[1]})"
    if unit:
        return f"{name} ({unit})"
    return name


def build_specialist_system(area_name: str, area_cfg: dict, topology: dict) -> str:
    site = topology.get("site", "Plant")
    facility = topology.get("facility", "WTP")
    eq_types = topology.get("equipment_types", {})
    imap = _inst_type_map(topology)

    instances = area_cfg.get("instances", [])
    description = area_cfg.get("description", "")

    by_type: dict[str, list[str]] = {}
    for inst_id in instances:
        eq_type = imap.get(inst_id, "Unknown")
        by_type.setdefault(eq_type, []).append(inst_id)

    scope_lines = []
    for eq_type, inst_ids in by_type.items():
        attrs = eq_types.get(eq_type, {}).get("attributes", {})
        attr_str = ", ".join(_fmt_attr(n, c) for n, c in attrs.items())
        scope_lines.append(f"  {', '.join(inst_ids)}\n    Attributes: {attr_str}")

    mqtt_lines = []
    for eq_type in by_type:
        mqtt_lines.append(f"  {site}/{facility}/{eq_type}/<Instance>/<Attribute>")

    heuristic_lines = []
    for eq_type in by_type:
        faults = eq_types.get(eq_type, {}).get("faults", {})
        if isinstance(faults, dict):
            for fault_cfg in faults.values():
                if isinstance(fault_cfg, dict) and "heuristic" in fault_cfg:
                    heuristic_lines.append(f"  - {fault_cfg['heuristic']}")

    scope_block = "\n".join(scope_lines)
    mqtt_block = "\n".join(mqtt_lines)
    heuristic_block = (
        "\n".join(heuristic_lines)
        or "  - Check for deviations from normal operating ranges"
    )
    description_block = f"\n\nArea context: {description}" if description else ""

    return (
        f"You are the {area_name} diagnostic specialist for a water treatment plant."
        f"{description_block}\n\n"
        f"Your scope covers ONLY these process units:\n{scope_block}\n\n"
        f"Tools available: MQTT (live reads) and InfluxDB (historical queries).\n"
        f"Do NOT use OPC-UA tools even if listed — they are redundant here.\n\n"
        f"MQTT topic root:\n{mqtt_block}\n"
        f"InfluxDB: call list_measurements first if unsure of available data.\n\n"
        f"Diagnostic approach:\n"
        f"1. Read current values for all units in scope via MQTT\n"
        f"2. Check for anomalies:\n{heuristic_block}\n"
        f"3. Query InfluxDB for recent trends if current readings are ambiguous\n"
        f"4. Compare units of the same type — single-unit fault vs multiple suggests different root causes\n\n"
        f"Always read actual values before making any assertions."
    )


def build_specialists(topology: dict | None = None) -> list[dict]:
    if topology is None:
        topology = _load()

    _SOURCE_PREFIXES = {
        "mqtt": ("mqtt__",),
        "influxdb": ("influxdb__",),
    }

    specialists = []
    for area_name, area_cfg in topology.get("process_areas", {}).items():
        data_sources = area_cfg.get("data_sources", ["mqtt", "influxdb"])
        tool_prefixes = tuple(
            p for src in data_sources for p in _SOURCE_PREFIXES.get(src, ())
        )
        specialists.append(
            {
                "name": area_name.lower(),
                "label": area_name,
                "unit_names": area_cfg.get("instances", []),
                "tool_prefixes": tool_prefixes,
                "system": build_specialist_system(area_name, area_cfg, topology),
            }
        )

    # Read-only memory tools for Historian — full names used as exact-match "prefixes".
    # Write tools (record_incident, record_observation, link_incident_precedes,
    # append_specialist_memory) are intentionally excluded; multi_agent_loop.py
    # handles all writes at session end.
    _MEMORY_READ_TOOLS = (
        "memory__run_correlation",
        "memory__get_equipment_history",
        "memory__query_graph",
        "memory__get_topology",
        "memory__get_specialist_context",
        "memory__get_writable_attributes",
        "memory__get_specialist_memory",
    )

    hist_cfg = topology.get("specialists", {}).get("historian", {})
    hist_sources = hist_cfg.get("data_sources", ["influxdb"])
    hist_prefixes = tuple(
        p for src in hist_sources for p in _SOURCE_PREFIXES.get(src, ())
    )
    if "memory" in hist_sources:
        hist_prefixes = hist_prefixes + _MEMORY_READ_TOOLS
    specialists.append(
        {
            "name": "historian",
            "label": "Historian",
            "unit_names": [],
            "tool_prefixes": hist_prefixes,
            "system": _HISTORIAN_SYSTEM,
        }
    )

    return specialists


def build_orchestrator_system(specialists: list[dict]) -> str:
    specialist_labels = ", ".join(s["label"] for s in specialists)
    return f"""You are the orchestrator for a multi-agent water treatment plant diagnostic system.

You will receive the user's diagnostic question followed by findings from these
specialist agents: {specialist_labels}.

Your job is to synthesize these findings into a single coherent diagnostic response:
- Identify the most significant anomalies or faults across all subsystems
- Note cross-specialist correlations (e.g. low raw water flow + rising clarifier turbidity)
- State overall plant health clearly
- Prioritize actionable findings
- If a specialist reported Status: Error or Status: Unknown, note the gap in coverage

Do not make up data. Only synthesize what the specialists reported.
Respond in plain text with markdown formatting.

── Control actions ────────────────────────────────────────────────────────────
If the synthesis reveals a clear fault requiring immediate corrective action,
call the control__propose_action tool. Do this SILENTLY — do not write "I am
proposing an action" or any similar text before the tool call. Just call it.

Writing about a proposed action in text without calling the tool is a protocol
violation. The tool IS the proposal — text is not.

Only propose when evidence is strong; do not propose for Normal status or minor
anomalies.

Tool parameters: description (str), action_type ("setpoint_adjustment"|"fault_clear"),
target (unit name), value (new value or empty string for fault_clear).

After the tool confirms operator approval, call control__set_setpoint or
control__clear_fault to execute. Never execute without prior approval."""
