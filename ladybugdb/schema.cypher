// ============================================================
// FieldWorks Topology Schema for LadybugDB
// Waterworks-AI Reference Implementation
// ============================================================
// Install: brew install ladybug  (or pip install ladybug-client)
// Run:     lbug -p ./fieldworks.db
// Load:    :source schema.cypher
// ============================================================


// ── NODE TABLES ──────────────────────────────────────────────

// The facility — top level node, one per deployment
CREATE NODE TABLE Facility (
    id           STRING PRIMARY KEY,
    name         STRING,
    description  STRING,
    timezone     STRING,
    units_system STRING
);

// Process areas — map to Specialist agents
CREATE NODE TABLE ProcessArea (
    id               STRING PRIMARY KEY,
    name             STRING,
    description      STRING,
    specialist_prompt STRING    // Area-level context injected into specialist system prompt
);

// Equipment types — class definitions, defined once
CREATE NODE TABLE EquipmentType (
    id          STRING PRIMARY KEY,
    name        STRING,
    description STRING
);

// Equipment instances — deployed equipment, one per physical unit
CREATE NODE TABLE Equipment (
    id           STRING PRIMARY KEY,
    name         STRING,
    description  STRING,
    commissioned DATE,
    notes        STRING         // Operational history; persists across sessions
);

// Attributes — measurable properties, defined on a type
CREATE NODE TABLE Attribute (
    id                  STRING PRIMARY KEY,
    name                STRING,
    description         STRING,
    units               STRING,
    normal_range_min    DOUBLE,
    normal_range_max    DOUBLE,
    normal_range_desc   STRING,
    writable            BOOLEAN,
    requires_confirmation BOOLEAN,   // True = operator approval required before write
    write_limit_min     DOUBLE,      // Hard lower bound enforced by control-mcp
    write_limit_max     DOUBLE       // Hard upper bound enforced by control-mcp
);

// Tag bindings — join between topology and the protocol surface
CREATE NODE TABLE TagBinding (
    id         STRING PRIMARY KEY,
    tag_id     STRING,
    confidence STRING,    // verified | inferred | suspect
    notes      STRING
);

// Fault modes — failure patterns, defined on a type
CREATE NODE TABLE FaultMode (
    id          STRING PRIMARY KEY,
    name        STRING,
    description STRING,
    severity    STRING    // advisory | warning | critical
);

// ── DYNAMIC / LEARNED LAYER ───────────────────────────────────

// A diagnostic session that produced a structured finding
CREATE NODE TABLE Incident (
    id         STRING PRIMARY KEY,
    session_id STRING,
    timestamp  TIMESTAMP,
    diagnosis  STRING,
    confidence DOUBLE,
    status     STRING,    // normal | anomaly_detected | fault_detected
    outcome    STRING     // monitoring | action_taken | recovered | unresolved
);

// Something a specialist learned that should persist across sessions
CREATE NODE TABLE Observation (
    id         STRING PRIMARY KEY,
    session_id STRING,
    timestamp  TIMESTAMP,
    text       STRING,
    confidence DOUBLE,
    specialist STRING
);

// An operator decision — mirrors action_events in SQLite, queryable by graph traversal
CREATE NODE TABLE OperatorDecision (
    id          STRING PRIMARY KEY,
    session_id  STRING,
    timestamp   TIMESTAMP,
    action_type STRING,
    value       STRING,
    decision    STRING,    // approved | denied
    operator_id STRING
);


// ── RELATIONSHIP TABLES ──────────────────────────────────────

// Structural relationships
CREATE REL TABLE CONTAINS_AREA      (FROM Facility TO ProcessArea);
CREATE REL TABLE CONTAINS_EQUIPMENT (FROM ProcessArea TO Equipment);
CREATE REL TABLE IS_TYPE            (FROM Equipment TO EquipmentType);
CREATE REL TABLE DEFINES_ATTRIBUTE  (FROM EquipmentType TO Attribute);
CREATE REL TABLE HAS_FAULT_MODE     (FROM EquipmentType TO FaultMode);
CREATE REL TABLE AFFECTS            (FROM FaultMode TO Attribute);  // Diagnostic indicators
CREATE REL TABLE BINDS_ATTRIBUTE    (FROM Equipment TO TagBinding, attribute_id STRING);
CREATE REL TABLE BINDING_OF         (FROM TagBinding TO Attribute);
CREATE REL TABLE FEEDS_INTO         (FROM ProcessArea TO ProcessArea, description STRING);

// Dynamic / learned relationships
CREATE REL TABLE INCIDENT_ON        (FROM Incident TO Equipment);
CREATE REL TABLE CONSISTENT_WITH    (FROM Incident TO FaultMode);
CREATE REL TABLE OBSERVATION_ON     (FROM Observation TO Equipment);
CREATE REL TABLE DECISION_ON        (FROM OperatorDecision TO Equipment);
CREATE REL TABLE PRECEDES           (FROM Incident TO Incident, hours_apart DOUBLE);
// PRECEDES: (A)-[:PRECEDES {hours_apart: X}]->(B) = A occurred X hours before B
// Query pattern: MATCH (cause)-[:PRECEDES]->(effect) to find causality chains


// ============================================================
// SEED DATA — Waterworks-AI Reference Deployment
// ============================================================

// ── Facility ─────────────────────────────────────────────────
CREATE (:Facility {
    id: "wtp-riverside-01",
    name: "Riverside Water Treatment Plant",
    description: "Municipal water treatment facility, 45 MGD capacity",
    timezone: "America/Chicago",
    units_system: "metric"
});

// ── Process areas ────────────────────────────────────────────
CREATE (:ProcessArea {
    id: "intake",
    name: "Raw Water Intake",
    description: "Screens and pumps raw water from the source into the treatment process.",
    specialist_prompt: "This plant draws from a river source with seasonal turbidity variation. During spring runoff (March–May) and storm events, turbidity at intake can spike above 50 NTU. Correlate intake turbidity with downstream clarifier performance."
});

CREATE (:ProcessArea {
    id: "treatment",
    name: "Treatment",
    description: "Coagulation, filtration, chemical dosing, and UV disinfection.",
    specialist_prompt: "Chlorination and UV disinfection run in series. Both barriers must be simultaneously active for regulatory compliance. A failure in either without compensating action from the other triggers a distribution advisory. Clarifier turbidity above 4 NTU warrants immediate investigation before water advances to distribution."
});

CREATE (:ProcessArea {
    id: "distribution",
    name: "Treated Water Distribution",
    description: "Pumping of treated water to the distribution network.",
    specialist_prompt: "High service pumps serve residential pressure zones. Minimum 40 PSI required at discharge. HighService_02 has a recurring pressure drift history — compare against HighService_01 readings before diagnosing transmitter vs. mechanical fault. Finished water tank level below 30% triggers demand-response protocol."
});

// Facility → areas
MATCH (f:Facility {id: "wtp-riverside-01"}), (a:ProcessArea)
CREATE (f)-[:CONTAINS_AREA]->(a);

// Process flow
MATCH (a1:ProcessArea {id: "intake"}),    (a2:ProcessArea {id: "treatment"})
CREATE (a1)-[:FEEDS_INTO {description: "Raw water flows from intake to treatment"}]->(a2);

MATCH (a2:ProcessArea {id: "treatment"}), (a3:ProcessArea {id: "distribution"})
CREATE (a2)-[:FEEDS_INTO {description: "Treated water flows to distribution"}]->(a3);


// ── Equipment types ──────────────────────────────────────────
CREATE (:EquipmentType {
    id: "centrifugal_pump",
    name: "Centrifugal Pump",
    description: "Moves water through the process via impeller rotation."
});
CREATE (:EquipmentType {
    id: "uv_bank",
    name: "UV Disinfection Bank",
    description: "Provides UV disinfection of treated water before distribution."
});
CREATE (:EquipmentType {
    id: "chemical_dosing_pump",
    name: "Chemical Dosing Pump",
    description: "Delivers chemical treatment agents at controlled flow rates."
});
CREATE (:EquipmentType {
    id: "clarifier",
    name: "Clarifier",
    description: "Settling tank that removes suspended solids before filtration."
});
CREATE (:EquipmentType {
    id: "storage_tank",
    name: "Storage Tank",
    description: "Stores treated water with continuous quality monitoring before distribution."
});


// ── Attributes — centrifugal pump ────────────────────────────
CREATE (:Attribute {
    id: "pump_flow", name: "Flow",
    units: "L/min", normal_range_min: 180.0, normal_range_max: 350.0,
    description: "Volumetric flow rate through the pump.",
    writable: false, requires_confirmation: false,
    write_limit_min: 0.0, write_limit_max: 0.0
});
CREATE (:Attribute {
    id: "pump_pressure", name: "Pressure",
    units: "bar", normal_range_min: 3.5, normal_range_max: 8.5,
    description: "Discharge pressure.",
    writable: false, requires_confirmation: false,
    write_limit_min: 0.0, write_limit_max: 0.0
});
CREATE (:Attribute {
    id: "pump_power", name: "Power",
    units: "kW", normal_range_min: 10.0, normal_range_max: 70.0,
    description: "Motor power consumption.",
    writable: false, requires_confirmation: false,
    write_limit_min: 0.0, write_limit_max: 0.0
});
CREATE (:Attribute {
    id: "pump_running", name: "Running",
    units: "", normal_range_min: 0.0, normal_range_max: 1.0,
    description: "Run status. 1 = running, 0 = stopped.",
    writable: false, requires_confirmation: false,
    write_limit_min: 0.0, write_limit_max: 0.0
});

MATCH (t:EquipmentType {id: "centrifugal_pump"}), (a:Attribute)
WHERE a.id IN ["pump_flow", "pump_pressure", "pump_power", "pump_running"]
CREATE (t)-[:DEFINES_ATTRIBUTE]->(a);


// ── Attributes — UV bank ─────────────────────────────────────
CREATE (:Attribute {
    id: "uv_intensity", name: "Intensity",
    units: "%", normal_range_min: 80.0, normal_range_max: 100.0,
    description: "UV lamp intensity as percentage of rated output.",
    writable: false, requires_confirmation: false,
    write_limit_min: 0.0, write_limit_max: 0.0
});
CREATE (:Attribute {
    id: "uv_lamp_hours", name: "LampHours",
    units: "hrs", normal_range_min: 0.0, normal_range_max: 9000.0,
    description: "Cumulative lamp operating hours. Replace at 8000–10000 hrs depending on manufacturer.",
    writable: false, requires_confirmation: false,
    write_limit_min: 0.0, write_limit_max: 0.0
});
CREATE (:Attribute {
    id: "uv_running", name: "Running",
    units: "", normal_range_min: 0.0, normal_range_max: 1.0,
    description: "Run status.",
    writable: false, requires_confirmation: false,
    write_limit_min: 0.0, write_limit_max: 0.0
});

MATCH (t:EquipmentType {id: "uv_bank"}), (a:Attribute)
WHERE a.id IN ["uv_intensity", "uv_lamp_hours", "uv_running"]
CREATE (t)-[:DEFINES_ATTRIBUTE]->(a);


// ── Attributes — chemical dosing pump ───────────────────────
CREATE (:Attribute {
    id: "dosing_flowrate", name: "FlowRate",
    units: "L/h", normal_range_min: 4.5, normal_range_max: 5.5,
    description: "Chemical delivery flow rate.",
    writable: false, requires_confirmation: false,
    write_limit_min: 0.0, write_limit_max: 0.0
});
CREATE (:Attribute {
    id: "dosing_tanklevel", name: "TankLevel",
    units: "%", normal_range_min: 10.0, normal_range_max: 100.0,
    description: "Chemical supply tank level. Below 10% triggers replenishment alert.",
    writable: false, requires_confirmation: false,
    write_limit_min: 0.0, write_limit_max: 0.0
});
CREATE (:Attribute {
    id: "dosing_running", name: "Running",
    units: "", normal_range_min: 0.0, normal_range_max: 1.0,
    description: "Run status.",
    writable: false, requires_confirmation: false,
    write_limit_min: 0.0, write_limit_max: 0.0
});
CREATE (:Attribute {
    id: "dosing_setpoint", name: "Setpoint",
    units: "L/h", normal_range_min: 4.5, normal_range_max: 5.5,
    description: "Target chemical delivery rate. Write requires operator approval.",
    writable: true, requires_confirmation: true,
    write_limit_min: 2.0, write_limit_max: 8.0
});

MATCH (t:EquipmentType {id: "chemical_dosing_pump"}), (a:Attribute)
WHERE a.id IN ["dosing_flowrate", "dosing_tanklevel", "dosing_running", "dosing_setpoint"]
CREATE (t)-[:DEFINES_ATTRIBUTE]->(a);


// ── Attributes — clarifier ───────────────────────────────────
CREATE (:Attribute {
    id: "clarifier_level", name: "Level",
    units: "%", normal_range_min: 20.0, normal_range_max: 90.0,
    description: "Water level as percentage of capacity.",
    writable: false, requires_confirmation: false,
    write_limit_min: 0.0, write_limit_max: 0.0
});
CREATE (:Attribute {
    id: "clarifier_turbidity", name: "Turbidity",
    units: "NTU", normal_range_min: 0.0, normal_range_max: 4.0,
    description: "Settled water clarity. Above 4 NTU warrants investigation before advancing to filtration.",
    writable: false, requires_confirmation: false,
    write_limit_min: 0.0, write_limit_max: 0.0
});

MATCH (t:EquipmentType {id: "clarifier"}), (a:Attribute)
WHERE a.id IN ["clarifier_level", "clarifier_turbidity"]
CREATE (t)-[:DEFINES_ATTRIBUTE]->(a);


// ── Attributes — storage tank ────────────────────────────────
CREATE (:Attribute {
    id: "storage_level", name: "Level",
    units: "%", normal_range_min: 20.0, normal_range_max: 90.0,
    description: "Water level as percentage of capacity.",
    writable: false, requires_confirmation: false,
    write_limit_min: 0.0, write_limit_max: 0.0
});
CREATE (:Attribute {
    id: "storage_turbidity", name: "Turbidity",
    units: "NTU", normal_range_min: 0.0, normal_range_max: 1.0,
    description: "Finished water clarity. Above 1 NTU indicates treatment failure or contamination.",
    writable: false, requires_confirmation: false,
    write_limit_min: 0.0, write_limit_max: 0.0
});
CREATE (:Attribute {
    id: "storage_ph", name: "pH",
    units: "pH", normal_range_min: 6.5, normal_range_max: 8.5,
    description: "Water pH. Regulatory range 6.5–8.5. Deviation may indicate dosing failure.",
    writable: false, requires_confirmation: false,
    write_limit_min: 0.0, write_limit_max: 0.0
});

MATCH (t:EquipmentType {id: "storage_tank"}), (a:Attribute)
WHERE a.id IN ["storage_level", "storage_turbidity", "storage_ph"]
CREATE (t)-[:DEFINES_ATTRIBUTE]->(a);


// ── Fault modes — centrifugal pump ───────────────────────────
CREATE (:FaultMode {
    id: "pump_bearing_wear", name: "Bearing Wear", severity: "warning",
    description: "Bearing wear presents as a gradual increase in vibration over hours to days. Motor current rises as mechanical resistance grows. Common causes: inadequate lubrication, contamination, or end-of-service-life."
});
CREATE (:FaultMode {
    id: "pump_cavitation", name: "Cavitation", severity: "warning",
    description: "Cavitation presents as erratic discharge pressure with high-frequency vibration. Motor current becomes unstable. Causes rapid impeller damage if sustained. Common causes: insufficient suction head or air entrainment."
});
CREATE (:FaultMode {
    id: "pump_seal_failure", name: "Seal Failure", severity: "critical",
    description: "Seal failure presents as a sudden drop in discharge pressure accompanied by a drop in motor current as the pump loses prime. Requires immediate shutdown. Do not restart without seal inspection and replacement."
});
CREATE (:FaultMode {
    id: "pump_run_status_anomaly", name: "Run Status Anomaly", severity: "advisory",
    description: "Pump reports stopped but shows non-zero flow or power readings. May indicate sensor drift, stale register values, or a control signal propagation failure."
});
CREATE (:FaultMode {
    id: "pump_suction_starvation", name: "Suction Starvation", severity: "warning",
    description: "Supply restriction to a running pump. Flow ramps toward zero while Running stays True. Pressure becomes erratic. Common causes: closed upstream valve, blocked intake screen, or low reservoir level."
});
CREATE (:FaultMode {
    id: "pump_pressure_drift", name: "Pressure Drift", severity: "advisory",
    description: "Reported pressure diverges progressively from true value. Indicates transmitter calibration drift. Flow and power remain normal. Verify with secondary measurement before taking process action."
});

MATCH (t:EquipmentType {id: "centrifugal_pump"}), (f:FaultMode)
WHERE f.id IN ["pump_bearing_wear", "pump_cavitation", "pump_seal_failure",
               "pump_run_status_anomaly", "pump_suction_starvation", "pump_pressure_drift"]
CREATE (t)-[:HAS_FAULT_MODE]->(f);

MATCH (f:FaultMode {id: "pump_cavitation"}), (a:Attribute)
WHERE a.id IN ["pump_pressure", "pump_power"]
CREATE (f)-[:AFFECTS]->(a);

MATCH (f:FaultMode {id: "pump_seal_failure"}), (a:Attribute)
WHERE a.id IN ["pump_pressure", "pump_power"]
CREATE (f)-[:AFFECTS]->(a);

MATCH (f:FaultMode {id: "pump_run_status_anomaly"}), (a:Attribute)
WHERE a.id IN ["pump_running", "pump_flow", "pump_power"]
CREATE (f)-[:AFFECTS]->(a);

MATCH (f:FaultMode {id: "pump_suction_starvation"}), (a:Attribute)
WHERE a.id IN ["pump_flow", "pump_pressure"]
CREATE (f)-[:AFFECTS]->(a);

MATCH (f:FaultMode {id: "pump_pressure_drift"}), (a:Attribute)
WHERE a.id IN ["pump_pressure"]
CREATE (f)-[:AFFECTS]->(a);


// ── Fault modes — UV bank ────────────────────────────────────
CREATE (:FaultMode {
    id: "uv_lamp_eol", name: "Lamp End of Life", severity: "warning",
    description: "UV lamp approaching or exceeding manufacturer replacement interval. Intensity may still read acceptable while actual germicidal effectiveness is degraded. Plan replacement before lamp hours exceed threshold."
});
CREATE (:FaultMode {
    id: "uv_intensity_drop", name: "Intensity Drop", severity: "critical",
    description: "UV intensity falling below 80% threshold. Active disinfection barrier is compromised. If chlorine dosing is also reduced or offline, distribution network has no disinfection residual."
});
CREATE (:FaultMode {
    id: "uv_lamp_failure", name: "Lamp Failure", severity: "critical",
    description: "Sudden lamp failure. Intensity drops to near zero immediately. Disinfection barrier lost. Requires immediate lamp replacement or switching to backup UV bank."
});

MATCH (t:EquipmentType {id: "uv_bank"}), (f:FaultMode)
WHERE f.id IN ["uv_lamp_eol", "uv_intensity_drop", "uv_lamp_failure"]
CREATE (t)-[:HAS_FAULT_MODE]->(f);

MATCH (f:FaultMode {id: "uv_lamp_eol"}), (a:Attribute)
WHERE a.id IN ["uv_intensity", "uv_lamp_hours"]
CREATE (f)-[:AFFECTS]->(a);

MATCH (f:FaultMode {id: "uv_intensity_drop"}), (a:Attribute)
WHERE a.id IN ["uv_intensity"]
CREATE (f)-[:AFFECTS]->(a);

MATCH (f:FaultMode {id: "uv_lamp_failure"}), (a:Attribute)
WHERE a.id IN ["uv_intensity", "uv_running"]
CREATE (f)-[:AFFECTS]->(a);


// ── Fault modes — chemical dosing pump ──────────────────────
CREATE (:FaultMode {
    id: "dosing_blockage", name: "Dosing Blockage", severity: "warning",
    description: "Discharge line obstruction. FlowRate ramps to zero over ~50s while Running stays True. Check inline strainer and discharge tubing for crystallisation or debris."
});
CREATE (:FaultMode {
    id: "dosing_tank_empty", name: "Chemical Tank Empty", severity: "warning",
    description: "Chemical supply exhausted. TankLevel depletes to zero over ~130s. No chemical delivery possible until tank is replenished."
});
CREATE (:FaultMode {
    id: "dosing_run_status_anomaly", name: "Run Status Anomaly", severity: "advisory",
    description: "Pump reports running but FlowRate reads near zero. May indicate feedback bit stuck or suction issue. Verify physical pump state."
});

MATCH (t:EquipmentType {id: "chemical_dosing_pump"}), (f:FaultMode)
WHERE f.id IN ["dosing_blockage", "dosing_tank_empty", "dosing_run_status_anomaly"]
CREATE (t)-[:HAS_FAULT_MODE]->(f);

MATCH (f:FaultMode {id: "dosing_blockage"}), (a:Attribute)
WHERE a.id IN ["dosing_flowrate", "dosing_running"]
CREATE (f)-[:AFFECTS]->(a);

MATCH (f:FaultMode {id: "dosing_tank_empty"}), (a:Attribute)
WHERE a.id IN ["dosing_tanklevel", "dosing_flowrate"]
CREATE (f)-[:AFFECTS]->(a);

MATCH (f:FaultMode {id: "dosing_run_status_anomaly"}), (a:Attribute)
WHERE a.id IN ["dosing_running", "dosing_flowrate"]
CREATE (f)-[:AFFECTS]->(a);


// ── Fault modes — clarifier ──────────────────────────────────
CREATE (:FaultMode {
    id: "clarifier_level_sensor_fault", name: "Level Sensor Fault", severity: "advisory",
    description: "Level transmitter noise. Reported level oscillates ±20% around true value. Verify with secondary measurement. Common causes: signal cable interference or transmitter power supply issue."
});
CREATE (:FaultMode {
    id: "clarifier_turbidity_spike", name: "Turbidity Spike", severity: "warning",
    description: "Turbidity climbing above 4 NTU indicates contamination or sedimentation failure. Water should not advance to filtration until turbidity returns to normal range."
});

MATCH (t:EquipmentType {id: "clarifier"}), (f:FaultMode)
WHERE f.id IN ["clarifier_level_sensor_fault", "clarifier_turbidity_spike"]
CREATE (t)-[:HAS_FAULT_MODE]->(f);

MATCH (f:FaultMode {id: "clarifier_level_sensor_fault"}), (a:Attribute {id: "clarifier_level"})
CREATE (f)-[:AFFECTS]->(a);

MATCH (f:FaultMode {id: "clarifier_turbidity_spike"}), (a:Attribute {id: "clarifier_turbidity"})
CREATE (f)-[:AFFECTS]->(a);


// ── Fault modes — storage tank ───────────────────────────────
CREATE (:FaultMode {
    id: "storage_level_sensor_fault", name: "Level Sensor Fault", severity: "advisory",
    description: "Level transmitter noise. Reported level oscillates ±20% around true value. Verify with secondary measurement before triggering demand-response protocol."
});
CREATE (:FaultMode {
    id: "storage_turbidity_spike", name: "Turbidity Spike", severity: "warning",
    description: "Finished water turbidity above 1 NTU indicates treatment failure or contamination. Above 4 NTU requires immediate investigation and potential distribution hold."
});

MATCH (t:EquipmentType {id: "storage_tank"}), (f:FaultMode)
WHERE f.id IN ["storage_level_sensor_fault", "storage_turbidity_spike"]
CREATE (t)-[:HAS_FAULT_MODE]->(f);

MATCH (f:FaultMode {id: "storage_level_sensor_fault"}), (a:Attribute {id: "storage_level"})
CREATE (f)-[:AFFECTS]->(a);

MATCH (f:FaultMode {id: "storage_turbidity_spike"}), (a:Attribute {id: "storage_turbidity"})
CREATE (f)-[:AFFECTS]->(a);


// ── Equipment instances ──────────────────────────────────────
CREATE (:Equipment {
    id: "RawWater_01", name: "Raw Water Pump 1",
    commissioned: date('2019-03-15'),
    notes: "Replaced impeller 2024-11-02 following cavitation damage. Monitor suction conditions during high-demand periods."
});
CREATE (:Equipment {
    id: "RawWater_02", name: "Raw Water Pump 2",
    commissioned: date('2021-07-08'), notes: ""
});
CREATE (:Equipment {
    id: "HighService_01", name: "High Service Pump 1",
    commissioned: date('2020-05-10'), notes: ""
});
CREATE (:Equipment {
    id: "HighService_02", name: "High Service Pump 2",
    commissioned: date('2020-05-10'),
    notes: "Recurring pressure drift faults. Four events in past year, root cause not yet identified."
});
CREATE (:Equipment {
    id: "UV_01", name: "UV Bank 1",
    commissioned: date('2018-11-01'),
    notes: "Approaching lamp replacement threshold. Schedule before 5000 hours."
});
CREATE (:Equipment {
    id: "UV_02", name: "UV Bank 2",
    commissioned: date('2020-03-15'), notes: ""
});
CREATE (:Equipment {
    id: "Chlorine_01", name: "Chlorine Dosing Pump",
    commissioned: date('2019-06-01'),
    notes: "History of dosing blockage faults. Check inline strainer on each inspection."
});
CREATE (:Equipment {
    id: "Fluoride_01", name: "Fluoride Dosing Pump",
    commissioned: date('2019-06-01'), notes: ""
});
CREATE (:Equipment {
    id: "Clarifier_01", name: "Clarifier Tank",
    commissioned: date('2015-01-01'), notes: ""
});
CREATE (:Equipment {
    id: "FinishedWater_01", name: "Finished Water Tank",
    commissioned: date('2015-01-01'), notes: ""
});

// Assign types
MATCH (e:Equipment), (t:EquipmentType {id: "centrifugal_pump"})
WHERE e.id IN ["RawWater_01", "RawWater_02", "HighService_01", "HighService_02"]
CREATE (e)-[:IS_TYPE]->(t);

MATCH (e:Equipment), (t:EquipmentType {id: "uv_bank"})
WHERE e.id IN ["UV_01", "UV_02"]
CREATE (e)-[:IS_TYPE]->(t);

MATCH (e:Equipment), (t:EquipmentType {id: "chemical_dosing_pump"})
WHERE e.id IN ["Chlorine_01", "Fluoride_01"]
CREATE (e)-[:IS_TYPE]->(t);

MATCH (e:Equipment {id: "Clarifier_01"}),    (t:EquipmentType {id: "clarifier"})
CREATE (e)-[:IS_TYPE]->(t);

MATCH (e:Equipment {id: "FinishedWater_01"}),(t:EquipmentType {id: "storage_tank"})
CREATE (e)-[:IS_TYPE]->(t);

// Assign to process areas
MATCH (e:Equipment), (a:ProcessArea {id: "intake"})
WHERE e.id IN ["RawWater_01", "RawWater_02"]
CREATE (a)-[:CONTAINS_EQUIPMENT]->(e);

MATCH (e:Equipment), (a:ProcessArea {id: "treatment"})
WHERE e.id IN ["UV_01", "UV_02", "Chlorine_01", "Fluoride_01", "Clarifier_01"]
CREATE (a)-[:CONTAINS_EQUIPMENT]->(e);

MATCH (e:Equipment), (a:ProcessArea {id: "distribution"})
WHERE e.id IN ["HighService_01", "HighService_02", "FinishedWater_01"]
CREATE (a)-[:CONTAINS_EQUIPMENT]->(e);


// ── Tag bindings ─────────────────────────────────────────────
// Pattern: Plant/WTP/<Type>/<Instance>/<Attribute>
// All bindings verified against running simulator.

// RawWater_01
CREATE (:TagBinding { id: "bind_RW01_flow",     tag_id: "Plant/WTP/Pump/RawWater_01/Flow",     confidence: "verified", notes: "" });
CREATE (:TagBinding { id: "bind_RW01_pressure", tag_id: "Plant/WTP/Pump/RawWater_01/Pressure", confidence: "verified", notes: "" });
CREATE (:TagBinding { id: "bind_RW01_power",    tag_id: "Plant/WTP/Pump/RawWater_01/Power",    confidence: "verified", notes: "" });
CREATE (:TagBinding { id: "bind_RW01_running",  tag_id: "Plant/WTP/Pump/RawWater_01/Running",  confidence: "verified", notes: "" });

// RawWater_02
CREATE (:TagBinding { id: "bind_RW02_flow",     tag_id: "Plant/WTP/Pump/RawWater_02/Flow",     confidence: "verified", notes: "" });
CREATE (:TagBinding { id: "bind_RW02_pressure", tag_id: "Plant/WTP/Pump/RawWater_02/Pressure", confidence: "verified", notes: "" });
CREATE (:TagBinding { id: "bind_RW02_power",    tag_id: "Plant/WTP/Pump/RawWater_02/Power",    confidence: "verified", notes: "" });
CREATE (:TagBinding { id: "bind_RW02_running",  tag_id: "Plant/WTP/Pump/RawWater_02/Running",  confidence: "verified", notes: "" });

// HighService_01
CREATE (:TagBinding { id: "bind_HS01_flow",     tag_id: "Plant/WTP/Pump/HighService_01/Flow",     confidence: "verified", notes: "" });
CREATE (:TagBinding { id: "bind_HS01_pressure", tag_id: "Plant/WTP/Pump/HighService_01/Pressure", confidence: "verified", notes: "" });
CREATE (:TagBinding { id: "bind_HS01_power",    tag_id: "Plant/WTP/Pump/HighService_01/Power",    confidence: "verified", notes: "" });
CREATE (:TagBinding { id: "bind_HS01_running",  tag_id: "Plant/WTP/Pump/HighService_01/Running",  confidence: "verified", notes: "" });

// HighService_02
CREATE (:TagBinding { id: "bind_HS02_flow",     tag_id: "Plant/WTP/Pump/HighService_02/Flow",     confidence: "verified", notes: "" });
CREATE (:TagBinding { id: "bind_HS02_pressure", tag_id: "Plant/WTP/Pump/HighService_02/Pressure", confidence: "verified", notes: "" });
CREATE (:TagBinding { id: "bind_HS02_power",    tag_id: "Plant/WTP/Pump/HighService_02/Power",    confidence: "verified", notes: "" });
CREATE (:TagBinding { id: "bind_HS02_running",  tag_id: "Plant/WTP/Pump/HighService_02/Running",  confidence: "verified", notes: "" });

// UV_01
CREATE (:TagBinding { id: "bind_UV01_intensity",  tag_id: "Plant/WTP/UV/UV_01/Intensity",  confidence: "verified", notes: "" });
CREATE (:TagBinding { id: "bind_UV01_lamphours",  tag_id: "Plant/WTP/UV/UV_01/LampHours",  confidence: "verified", notes: "" });
CREATE (:TagBinding { id: "bind_UV01_running",    tag_id: "Plant/WTP/UV/UV_01/Running",    confidence: "verified", notes: "" });

// UV_02
CREATE (:TagBinding { id: "bind_UV02_intensity",  tag_id: "Plant/WTP/UV/UV_02/Intensity",  confidence: "verified", notes: "" });
CREATE (:TagBinding { id: "bind_UV02_lamphours",  tag_id: "Plant/WTP/UV/UV_02/LampHours",  confidence: "verified", notes: "" });
CREATE (:TagBinding { id: "bind_UV02_running",    tag_id: "Plant/WTP/UV/UV_02/Running",    confidence: "verified", notes: "" });

// Chlorine_01
CREATE (:TagBinding { id: "bind_CL01_flowrate",  tag_id: "Plant/WTP/Dosing/Chlorine_01/FlowRate",  confidence: "verified", notes: "" });
CREATE (:TagBinding { id: "bind_CL01_tanklevel", tag_id: "Plant/WTP/Dosing/Chlorine_01/TankLevel", confidence: "verified", notes: "" });
CREATE (:TagBinding { id: "bind_CL01_running",   tag_id: "Plant/WTP/Dosing/Chlorine_01/Running",   confidence: "verified", notes: "" });
CREATE (:TagBinding { id: "bind_CL01_setpoint",  tag_id: "Plant/WTP/Dosing/Chlorine_01/Setpoint",  confidence: "verified", notes: "" });

// Fluoride_01
CREATE (:TagBinding { id: "bind_FL01_flowrate",  tag_id: "Plant/WTP/Dosing/Fluoride_01/FlowRate",  confidence: "verified", notes: "" });
CREATE (:TagBinding { id: "bind_FL01_tanklevel", tag_id: "Plant/WTP/Dosing/Fluoride_01/TankLevel", confidence: "verified", notes: "" });
CREATE (:TagBinding { id: "bind_FL01_running",   tag_id: "Plant/WTP/Dosing/Fluoride_01/Running",   confidence: "verified", notes: "" });
CREATE (:TagBinding { id: "bind_FL01_setpoint",  tag_id: "Plant/WTP/Dosing/Fluoride_01/Setpoint",  confidence: "verified", notes: "" });

// Clarifier_01
CREATE (:TagBinding { id: "bind_CLA01_level",     tag_id: "Plant/WTP/Clarifier/Clarifier_01/Level",     confidence: "verified", notes: "" });
CREATE (:TagBinding { id: "bind_CLA01_turbidity", tag_id: "Plant/WTP/Clarifier/Clarifier_01/Turbidity", confidence: "verified", notes: "" });

// FinishedWater_01
CREATE (:TagBinding { id: "bind_FW01_level",     tag_id: "Plant/WTP/StorageTank/FinishedWater_01/Level",     confidence: "verified", notes: "" });
CREATE (:TagBinding { id: "bind_FW01_turbidity", tag_id: "Plant/WTP/StorageTank/FinishedWater_01/Turbidity", confidence: "verified", notes: "" });
CREATE (:TagBinding { id: "bind_FW01_ph",        tag_id: "Plant/WTP/StorageTank/FinishedWater_01/pH",        confidence: "verified", notes: "" });

// Wire bindings — pumps
MATCH (e:Equipment {id: "RawWater_01"}),  (b:TagBinding {id: "bind_RW01_flow"}),    (a:Attribute {id: "pump_flow"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "pump_flow"}]->(b);     CREATE (b)-[:BINDING_OF]->(a);
MATCH (e:Equipment {id: "RawWater_01"}),  (b:TagBinding {id: "bind_RW01_pressure"}),(a:Attribute {id: "pump_pressure"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "pump_pressure"}]->(b); CREATE (b)-[:BINDING_OF]->(a);
MATCH (e:Equipment {id: "RawWater_01"}),  (b:TagBinding {id: "bind_RW01_power"}),   (a:Attribute {id: "pump_power"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "pump_power"}]->(b);    CREATE (b)-[:BINDING_OF]->(a);
MATCH (e:Equipment {id: "RawWater_01"}),  (b:TagBinding {id: "bind_RW01_running"}), (a:Attribute {id: "pump_running"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "pump_running"}]->(b);  CREATE (b)-[:BINDING_OF]->(a);

MATCH (e:Equipment {id: "RawWater_02"}),  (b:TagBinding {id: "bind_RW02_flow"}),    (a:Attribute {id: "pump_flow"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "pump_flow"}]->(b);     CREATE (b)-[:BINDING_OF]->(a);
MATCH (e:Equipment {id: "RawWater_02"}),  (b:TagBinding {id: "bind_RW02_pressure"}),(a:Attribute {id: "pump_pressure"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "pump_pressure"}]->(b); CREATE (b)-[:BINDING_OF]->(a);
MATCH (e:Equipment {id: "RawWater_02"}),  (b:TagBinding {id: "bind_RW02_power"}),   (a:Attribute {id: "pump_power"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "pump_power"}]->(b);    CREATE (b)-[:BINDING_OF]->(a);
MATCH (e:Equipment {id: "RawWater_02"}),  (b:TagBinding {id: "bind_RW02_running"}), (a:Attribute {id: "pump_running"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "pump_running"}]->(b);  CREATE (b)-[:BINDING_OF]->(a);

MATCH (e:Equipment {id: "HighService_01"}),(b:TagBinding {id: "bind_HS01_flow"}),    (a:Attribute {id: "pump_flow"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "pump_flow"}]->(b);     CREATE (b)-[:BINDING_OF]->(a);
MATCH (e:Equipment {id: "HighService_01"}),(b:TagBinding {id: "bind_HS01_pressure"}),(a:Attribute {id: "pump_pressure"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "pump_pressure"}]->(b); CREATE (b)-[:BINDING_OF]->(a);
MATCH (e:Equipment {id: "HighService_01"}),(b:TagBinding {id: "bind_HS01_power"}),   (a:Attribute {id: "pump_power"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "pump_power"}]->(b);    CREATE (b)-[:BINDING_OF]->(a);
MATCH (e:Equipment {id: "HighService_01"}),(b:TagBinding {id: "bind_HS01_running"}), (a:Attribute {id: "pump_running"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "pump_running"}]->(b);  CREATE (b)-[:BINDING_OF]->(a);

MATCH (e:Equipment {id: "HighService_02"}),(b:TagBinding {id: "bind_HS02_flow"}),    (a:Attribute {id: "pump_flow"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "pump_flow"}]->(b);     CREATE (b)-[:BINDING_OF]->(a);
MATCH (e:Equipment {id: "HighService_02"}),(b:TagBinding {id: "bind_HS02_pressure"}),(a:Attribute {id: "pump_pressure"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "pump_pressure"}]->(b); CREATE (b)-[:BINDING_OF]->(a);
MATCH (e:Equipment {id: "HighService_02"}),(b:TagBinding {id: "bind_HS02_power"}),   (a:Attribute {id: "pump_power"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "pump_power"}]->(b);    CREATE (b)-[:BINDING_OF]->(a);
MATCH (e:Equipment {id: "HighService_02"}),(b:TagBinding {id: "bind_HS02_running"}), (a:Attribute {id: "pump_running"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "pump_running"}]->(b);  CREATE (b)-[:BINDING_OF]->(a);

// UV bindings
MATCH (e:Equipment {id: "UV_01"}),(b:TagBinding {id: "bind_UV01_intensity"}), (a:Attribute {id: "uv_intensity"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "uv_intensity"}]->(b);  CREATE (b)-[:BINDING_OF]->(a);
MATCH (e:Equipment {id: "UV_01"}),(b:TagBinding {id: "bind_UV01_lamphours"}), (a:Attribute {id: "uv_lamp_hours"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "uv_lamp_hours"}]->(b); CREATE (b)-[:BINDING_OF]->(a);
MATCH (e:Equipment {id: "UV_01"}),(b:TagBinding {id: "bind_UV01_running"}),   (a:Attribute {id: "uv_running"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "uv_running"}]->(b);    CREATE (b)-[:BINDING_OF]->(a);

MATCH (e:Equipment {id: "UV_02"}),(b:TagBinding {id: "bind_UV02_intensity"}), (a:Attribute {id: "uv_intensity"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "uv_intensity"}]->(b);  CREATE (b)-[:BINDING_OF]->(a);
MATCH (e:Equipment {id: "UV_02"}),(b:TagBinding {id: "bind_UV02_lamphours"}), (a:Attribute {id: "uv_lamp_hours"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "uv_lamp_hours"}]->(b); CREATE (b)-[:BINDING_OF]->(a);
MATCH (e:Equipment {id: "UV_02"}),(b:TagBinding {id: "bind_UV02_running"}),   (a:Attribute {id: "uv_running"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "uv_running"}]->(b);    CREATE (b)-[:BINDING_OF]->(a);

// Dosing bindings
MATCH (e:Equipment {id: "Chlorine_01"}),(b:TagBinding {id: "bind_CL01_flowrate"}), (a:Attribute {id: "dosing_flowrate"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "dosing_flowrate"}]->(b);  CREATE (b)-[:BINDING_OF]->(a);
MATCH (e:Equipment {id: "Chlorine_01"}),(b:TagBinding {id: "bind_CL01_tanklevel"}),(a:Attribute {id: "dosing_tanklevel"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "dosing_tanklevel"}]->(b); CREATE (b)-[:BINDING_OF]->(a);
MATCH (e:Equipment {id: "Chlorine_01"}),(b:TagBinding {id: "bind_CL01_running"}),  (a:Attribute {id: "dosing_running"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "dosing_running"}]->(b);   CREATE (b)-[:BINDING_OF]->(a);
MATCH (e:Equipment {id: "Chlorine_01"}),(b:TagBinding {id: "bind_CL01_setpoint"}), (a:Attribute {id: "dosing_setpoint"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "dosing_setpoint"}]->(b);  CREATE (b)-[:BINDING_OF]->(a);

MATCH (e:Equipment {id: "Fluoride_01"}),(b:TagBinding {id: "bind_FL01_flowrate"}), (a:Attribute {id: "dosing_flowrate"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "dosing_flowrate"}]->(b);  CREATE (b)-[:BINDING_OF]->(a);
MATCH (e:Equipment {id: "Fluoride_01"}),(b:TagBinding {id: "bind_FL01_tanklevel"}),(a:Attribute {id: "dosing_tanklevel"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "dosing_tanklevel"}]->(b); CREATE (b)-[:BINDING_OF]->(a);
MATCH (e:Equipment {id: "Fluoride_01"}),(b:TagBinding {id: "bind_FL01_running"}),  (a:Attribute {id: "dosing_running"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "dosing_running"}]->(b);   CREATE (b)-[:BINDING_OF]->(a);
MATCH (e:Equipment {id: "Fluoride_01"}),(b:TagBinding {id: "bind_FL01_setpoint"}), (a:Attribute {id: "dosing_setpoint"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "dosing_setpoint"}]->(b);  CREATE (b)-[:BINDING_OF]->(a);

// Clarifier bindings
MATCH (e:Equipment {id: "Clarifier_01"}),    (b:TagBinding {id: "bind_CLA01_level"}),    (a:Attribute {id: "clarifier_level"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "clarifier_level"}]->(b);     CREATE (b)-[:BINDING_OF]->(a);
MATCH (e:Equipment {id: "Clarifier_01"}),    (b:TagBinding {id: "bind_CLA01_turbidity"}),(a:Attribute {id: "clarifier_turbidity"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "clarifier_turbidity"}]->(b);  CREATE (b)-[:BINDING_OF]->(a);

// Storage tank bindings
MATCH (e:Equipment {id: "FinishedWater_01"}),(b:TagBinding {id: "bind_FW01_level"}),    (a:Attribute {id: "storage_level"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "storage_level"}]->(b);     CREATE (b)-[:BINDING_OF]->(a);
MATCH (e:Equipment {id: "FinishedWater_01"}),(b:TagBinding {id: "bind_FW01_turbidity"}),(a:Attribute {id: "storage_turbidity"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "storage_turbidity"}]->(b);  CREATE (b)-[:BINDING_OF]->(a);
MATCH (e:Equipment {id: "FinishedWater_01"}),(b:TagBinding {id: "bind_FW01_ph"}),       (a:Attribute {id: "storage_ph"})
CREATE (e)-[:BINDS_ATTRIBUTE {attribute_id: "storage_ph"}]->(b);         CREATE (b)-[:BINDING_OF]->(a);


// ============================================================
// EXAMPLE QUERIES
// ============================================================

// All equipment in an area with type
MATCH (a:ProcessArea {id: "intake"})-[:CONTAINS_EQUIPMENT]->(e:Equipment)-[:IS_TYPE]->(t:EquipmentType)
RETURN e.name, t.name, e.notes;

// All fault modes for treatment area, ordered by severity
MATCH (a:ProcessArea {id: "treatment"})-[:CONTAINS_EQUIPMENT]->(e:Equipment)
      -[:IS_TYPE]->(t:EquipmentType)-[:HAS_FAULT_MODE]->(f:FaultMode)
RETURN e.name, f.name, f.severity
ORDER BY f.severity;

// All writable attributes with approval requirements and limits
MATCH (e:Equipment)-[:BINDS_ATTRIBUTE]->(b:TagBinding)-[:BINDING_OF]->(a:Attribute {writable: true})
RETURN e.name, a.name, b.tag_id, a.requires_confirmation, a.write_limit_min, a.write_limit_max;

// Critical fault modes and exposed equipment
MATCH (t:EquipmentType)-[:HAS_FAULT_MODE]->(f:FaultMode {severity: "critical"})
      <-[:IS_TYPE]-(e:Equipment)
RETURN f.name, collect(e.name) AS exposed_equipment;

// Cross-area process flow
MATCH (a1:ProcessArea)-[:FEEDS_INTO]->(a2:ProcessArea)
RETURN a1.name AS upstream, a2.name AS downstream;

// Suspect or inferred bindings needing verification
MATCH (e:Equipment)-[:BINDS_ATTRIBUTE]->(b:TagBinding)
WHERE b.confidence IN ["suspect", "inferred"]
RETURN e.name, b.tag_id, b.confidence, b.notes;

// Equipment with operational notes
MATCH (e:Equipment) WHERE e.notes <> ""
RETURN e.name, e.notes;

// Incident causality chain — what followed a cavitation event?
MATCH (cause:Incident)-[:CONSISTENT_WITH]->(:FaultMode {id: "pump_cavitation"}),
      (cause)-[:PRECEDES {hours_apart: hours}]->(effect:Incident)
WHERE hours < 24
RETURN cause.timestamp, effect.diagnosis, effect.status, hours
ORDER BY hours;

// Operator denial patterns — what actions does the operator routinely deny?
MATCH (d:OperatorDecision {decision: "denied"})-[:DECISION_ON]->(e:Equipment)
RETURN e.name, d.action_type, count(*) AS denial_count
ORDER BY denial_count DESC;

// build_specialist_prompt() — everything a specialist needs for one area
// NOTE: Returns flat table; aggregate in Python before building prompt.
// See aggregate_specialist_query() in memory-mcp/query.py
MATCH (area:ProcessArea {id: "intake"})-[:CONTAINS_EQUIPMENT]->(e:Equipment)
      -[:IS_TYPE]->(t:EquipmentType)
OPTIONAL MATCH (t)-[:DEFINES_ATTRIBUTE]->(attr:Attribute)
OPTIONAL MATCH (t)-[:HAS_FAULT_MODE]->(fm:FaultMode)
OPTIONAL MATCH (fm)-[:AFFECTS]->(affected:Attribute)
OPTIONAL MATCH (e)-[:BINDS_ATTRIBUTE {attribute_id: attr.id}]->(b:TagBinding)
RETURN
    area.name AS process_area,
    area.specialist_prompt AS area_context,
    e.name AS equipment, e.notes AS equipment_notes,
    t.name AS equipment_type,
    attr.name AS attribute, attr.units AS units,
    attr.normal_range_min AS normal_min, attr.normal_range_max AS normal_max,
    b.tag_id AS tag_id, b.confidence AS binding_confidence,
    fm.name AS fault_mode, fm.severity AS fault_severity,
    fm.description AS fault_description
ORDER BY e.name, attr.name;
