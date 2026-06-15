"""
Static MQTT + OPC-UA snapshot for a legacy WTP installation.

Messiness types present:
  - Abbreviated attributes: RawWater_02 uses FLW/PRS/PWR/RUN instead of Flow/Pressure/Power/Running
  - Ghost tag: OldPump_03 — decommissioned pump, stale zero-value publish, absent from OPC-UA
  - Duplicate sensors: RawWater_01 has Flow + FlowPrimary + FlowBackup
  - Deprecated alias: Clarifier_01/TRBD alongside Clarifier_01/Turbidity
  - Non-standard depth: HS_Pump_1 published at 3 levels (WTP/HS_Pump_1/attr) instead of 5
  - Ambiguous equipment: ABB_Drive_01 has no equipment type in the template
  - Retired UV bank: UV_03 publishes constant 0.0 / false, not in OPC-UA
  - Vendor-prefixed namespace: HS_Pump_2 under Siemens/S7/Pump/
  - Missing required attr: pH absent from FinishedWater_01 MQTT stream (pH_raw/pH_units are non-standard)
  - Flat tags: wtp_rawpump_* — single-level, match no equipment pattern

OPC-UA covers only the well-maintained, still-active equipment. Decommissioned and
legacy-namespace instances are MQTT-only, which is the real-world pattern: OPC-UA servers
get cleaned up before MQTT bridges do.
"""

LEGACY_TOPICS: dict[str, str] = {
    # ── Clean pump — all standard attrs + duplicate flow sensors ────────────────
    "Plant/WTP/Pump/RawWater_01/Flow": "312.4",
    "Plant/WTP/Pump/RawWater_01/Pressure": "4.2",
    "Plant/WTP/Pump/RawWater_01/Power": "42.1",
    "Plant/WTP/Pump/RawWater_01/Running": "true",
    "Plant/WTP/Pump/RawWater_01/FlowPrimary": "313.1",
    "Plant/WTP/Pump/RawWater_01/FlowBackup": "310.8",
    # ── Abbreviated attribute names ──────────────────────────────────────────────
    "Plant/WTP/Pump/RawWater_02/FLW": "298.0",
    "Plant/WTP/Pump/RawWater_02/PRS": "4.0",
    "Plant/WTP/Pump/RawWater_02/PWR": "39.5",
    "Plant/WTP/Pump/RawWater_02/RUN": "1",
    # ── Ghost tag — decommissioned pump, stale zeros, no OPC-UA ─────────────────
    "Plant/WTP/Pump/OldPump_03/Flow": "0.0",
    "Plant/WTP/Pump/OldPump_03/Pressure": "0.0",
    # ── Non-standard depth (3 levels) — matches only via legacy_patterns ─────────
    "WTP/HS_Pump_1/Flow": "220.1",
    "WTP/HS_Pump_1/Pressure": "6.8",
    "WTP/HS_Pump_1/Running": "true",
    # ── Ambiguous equipment — no matching type in template ───────────────────────
    "Plant/WTP/Drive/ABB_Drive_01/ActualSpeed": "1450.0",
    "Plant/WTP/Drive/ABB_Drive_01/Torque": "85.0",
    "Plant/WTP/Drive/ABB_Drive_01/Running": "true",
    # ── Clarifier — clean + deprecated alias still publishing ────────────────────
    "Plant/WTP/Clarifier/Clarifier_01/Level": "62.3",
    "Plant/WTP/Clarifier/Clarifier_01/Turbidity": "2.1",
    "Plant/WTP/Clarifier/Clarifier_01/TRBD": "2.0",
    # ── Storage tank — pH absent (sensor offline); non-standard pH attrs present ─
    "Plant/WTP/StorageTank/FinishedWater_01/Level": "78.5",
    "Plant/WTP/StorageTank/FinishedWater_01/Turbidity": "0.4",
    "Plant/WTP/StorageTank/FinishedWater_01/pH_raw": "7.1",
    "Plant/WTP/StorageTank/FinishedWater_01/pH_units": "pH",
    # ── Dosing — clean ────────────────────────────────────────────────────────────
    "Plant/WTP/Dosing/Chlorine_01/FlowRate": "3.2",
    "Plant/WTP/Dosing/Chlorine_01/TankLevel": "68.0",
    "Plant/WTP/Dosing/Chlorine_01/Running": "true",
    # ── UV — active bank (clean) + retired bank (constant zero, no OPC-UA) ──────
    "Plant/WTP/UV/UV_01/Intensity": "92.4",
    "Plant/WTP/UV/UV_01/LampHours": "4312.0",
    "Plant/WTP/UV/UV_01/Running": "true",
    "Plant/WTP/UV/UV_03/Intensity": "0.0",
    "Plant/WTP/UV/UV_03/LampHours": "9999.0",
    "Plant/WTP/UV/UV_03/Running": "false",
    # ── Vendor-prefixed namespace — Siemens S7 OPC-UA bridge, wrong root ─────────
    "Siemens/S7/Pump/HS_Pump_2/Speed_rpm": "2900.0",
    "Siemens/S7/Pump/HS_Pump_2/Current_mA": "14.2",
    # ── Flat single-level legacy tags — match no equipment pattern ────────────────
    "wtp_rawpump_flow": "305.0",
    "wtp_rawpump_pressure": "4.1",
}

# OPC-UA covers modern, actively maintained equipment only.
# Absent: OldPump_03, HS_Pump_1, RawWater_02, UV_03, HS_Pump_2 (Siemens).
# This asymmetry (MQTT-present + OPC-UA-absent) is the real-world signal for
# decommissioned or legacy-namespace equipment.
LEGACY_OPCUA_NODES: list[str] = [
    "Objects/Plant/WTP/Pump/RawWater_01/Flow",
    "Objects/Plant/WTP/Pump/RawWater_01/Pressure",
    "Objects/Plant/WTP/Pump/RawWater_01/Running",
    "Objects/Plant/WTP/Clarifier/Clarifier_01/Level",
    "Objects/Plant/WTP/Clarifier/Clarifier_01/Turbidity",
    "Objects/Plant/WTP/Dosing/Chlorine_01/FlowRate",
    "Objects/Plant/WTP/Dosing/Chlorine_01/Running",
    "Objects/Plant/WTP/UV/UV_01/Intensity",
    "Objects/Plant/WTP/UV/UV_01/Running",
    "Objects/Plant/WTP/StorageTank/FinishedWater_01/Level",
]
