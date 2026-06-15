"""Fault injection for the WTP simulator.

Each FaultState instance is attached to one process unit. Calling apply() each
tick returns the (possibly transformed) value for a given attribute. Calling
tick() advances any internal ramp or drift state once per publish cycle.

Fault modes
-----------
Pumps
  normal              Clean random-walk signals.
  suction_starvation  Flow ramps toward zero over ~25 ticks, power follows,
                      pressure becomes erratic. Running stays True.
  run_status_fault    Running feedback reads True but pump is off — Flow and
                      Power near zero. Simulates a stuck discrete output.
  pressure_drift      Reported pressure diverges via a cumulative transmitter
                      offset. All other attrs normal.
  cavitation          Flow collapses unpredictably; pressure has rapid spikes.

Tanks
  level_sensor_fault  Level transmitter oscillates with large random noise.
                      Turbidity and other attrs unaffected.
  turbidity_spike     Sudden high-turbidity event (contamination / disturbance).

Dosing
  dosing_blockage     FlowRate ramps toward zero over ~25 ticks; pump Running
                      stays True. TankLevel normal (not consuming chemical).
  tank_empty          TankLevel depletes over time; FlowRate drops as level falls.
  run_status_fault    Shared with Pump — same behaviour (Running True, no flow).

UV
  lamp_degradation    Intensity gradually decreases over time (~50 ticks to ~20%).
  lamp_failure        Intensity drops to near-zero immediately; Running stays True.
"""

import random
from enum import Enum


class FaultMode(str, Enum):
    NORMAL = "normal"
    # Pump
    SUCTION_STARVATION = "suction_starvation"
    RUN_STATUS_FAULT = "run_status_fault"
    PRESSURE_DRIFT = "pressure_drift"
    CAVITATION = "cavitation"
    # Tank
    LEVEL_SENSOR_FAULT = "level_sensor_fault"
    TURBIDITY_SPIKE = "turbidity_spike"
    # Dosing
    DOSING_BLOCKAGE = "dosing_blockage"
    TANK_EMPTY = "tank_empty"
    # UV
    LAMP_DEGRADATION = "lamp_degradation"
    LAMP_FAILURE = "lamp_failure"


from topology import load as _load_topology


def _build_type_fault_modes(data: dict) -> dict[str, list[FaultMode]]:
    result = {}
    for eq_type, spec in data["equipment_types"].items():
        modes = [FaultMode.NORMAL]
        for fault_id in (
            spec["faults"].keys()
            if isinstance(spec["faults"], dict)
            else spec["faults"]
        ):
            try:
                modes.append(FaultMode(fault_id))
            except ValueError:
                pass  # fault in topology has no simulation code yet — skip silently
        result[eq_type] = modes
    return result


TYPE_FAULT_MODES: dict[str, list[FaultMode]] = _build_type_fault_modes(_load_topology())


class FaultState:
    def __init__(self) -> None:
        self.mode: FaultMode = FaultMode.NORMAL
        self._intensity: float = 0.0
        self._drift_offset: float = 0.0

    def set_mode(self, mode: FaultMode) -> None:
        if mode != self.mode:
            self.mode = mode
            self._intensity = 0.0
            self._drift_offset = 0.0

    def tick(self) -> None:
        """Advance internal state once per publish cycle, before apply() calls."""
        match self.mode:
            case FaultMode.SUCTION_STARVATION:
                self._intensity = min(1.0, self._intensity + 0.04)  # ~25 ticks to full
            case FaultMode.PRESSURE_DRIFT:
                self._drift_offset += random.uniform(0.05, 0.15)
            case FaultMode.DOSING_BLOCKAGE:
                self._intensity = min(1.0, self._intensity + 0.04)  # ~25 ticks to full
            case FaultMode.TANK_EMPTY:
                self._intensity = min(
                    1.0, self._intensity + 0.015
                )  # ~65 ticks to empty
            case FaultMode.LAMP_DEGRADATION:
                self._intensity = min(1.0, self._intensity + 0.016)  # ~60 ticks to ~20%

    def apply(self, attr: str, raw: float | bool) -> float | bool:
        match self.mode:
            case FaultMode.NORMAL:
                return raw
            case FaultMode.SUCTION_STARVATION:
                return self._starvation(attr, raw)
            case FaultMode.RUN_STATUS_FAULT:
                return self._run_status(attr, raw)
            case FaultMode.PRESSURE_DRIFT:
                return self._pressure_drift(attr, raw)
            case FaultMode.CAVITATION:
                return self._cavitation(attr, raw)
            case FaultMode.LEVEL_SENSOR_FAULT:
                return self._level_sensor(attr, raw)
            case FaultMode.TURBIDITY_SPIKE:
                return self._turbidity_spike(attr, raw)
            case FaultMode.DOSING_BLOCKAGE:
                return self._dosing_blockage(attr, raw)
            case FaultMode.TANK_EMPTY:
                return self._tank_empty(attr, raw)
            case FaultMode.LAMP_DEGRADATION:
                return self._lamp_degradation(attr, raw)
            case FaultMode.LAMP_FAILURE:
                return self._lamp_failure(attr, raw)
        return raw

    # ── Pump faults ───────────────────────────────────────────────────────────

    def _starvation(self, attr: str, raw: float | bool) -> float | bool:
        i = self._intensity
        if attr == "Running":
            return True
        if attr == "Flow":
            suppressed = float(raw) * (1.0 - i)
            return round(max(0.0, suppressed + random.uniform(-2.0, 2.0) * i), 2)
        if attr == "Power":
            return round(max(0.0, float(raw) * (1.0 - i * 0.85)), 2)
        if attr == "Pressure":
            return round(float(raw) + random.uniform(-3.0, 3.0) * i, 2)
        return raw

    def _run_status(self, attr: str, raw: float | bool) -> float | bool:
        if attr == "Running":
            return True
        if attr in ("Flow", "Power", "FlowRate"):
            return round(random.uniform(0.0, 1.0), 2)
        if attr == "Pressure":
            return round(random.uniform(0.0, 0.5), 2)
        return raw

    def _pressure_drift(self, attr: str, raw: float | bool) -> float | bool:
        if attr == "Pressure":
            noise = random.uniform(-0.1, 0.1)
            return round(float(raw) + self._drift_offset + noise, 2)
        return raw

    def _cavitation(self, attr: str, raw: float | bool) -> float | bool:
        if attr == "Running":
            return True
        if attr == "Flow":
            if random.random() < 0.15:
                return round(float(raw) * random.uniform(0.0, 0.2), 2)
            return round(float(raw) * random.uniform(0.6, 1.4), 2)
        if attr == "Pressure":
            return round(float(raw) * random.uniform(0.7, 1.3), 2)
        if attr == "Power":
            return round(float(raw) * random.uniform(1.0, 1.15), 2)
        return raw

    # ── Tank faults ───────────────────────────────────────────────────────────

    def _level_sensor(self, attr: str, raw: float | bool) -> float | bool:
        if attr == "Level":
            noise = random.uniform(-20.0, 20.0)
            return round(max(0.0, min(100.0, float(raw) + noise)), 1)
        return raw

    def _turbidity_spike(self, attr: str, raw: float | bool) -> float | bool:
        if attr == "Turbidity":
            return round(10.0 + random.uniform(-1.5, 4.0), 2)
        return raw

    # ── Dosing faults ─────────────────────────────────────────────────────────

    def _dosing_blockage(self, attr: str, raw: float | bool) -> float | bool:
        if attr == "FlowRate":
            return round(max(0.0, float(raw) * (1.0 - self._intensity)), 2)
        if attr == "Running":
            return True
        return raw

    def _tank_empty(self, attr: str, raw: float | bool) -> float | bool:
        if attr == "TankLevel":
            return round(max(0.0, float(raw) * (1.0 - self._intensity * 1.1)), 1)
        if attr == "FlowRate":
            return round(max(0.0, float(raw) * (1.0 - self._intensity)), 2)
        return raw

    # ── UV faults ─────────────────────────────────────────────────────────────

    def _lamp_degradation(self, attr: str, raw: float | bool) -> float | bool:
        if attr == "Intensity":
            degraded = max(0.0, float(raw) * (1.0 - self._intensity * 0.8))
            return round(degraded + random.uniform(-0.5, 0.3), 1)
        return raw

    def _lamp_failure(self, attr: str, raw: float | bool) -> float | bool:
        if attr == "Intensity":
            return round(random.uniform(0.0, 2.5), 1)
        if attr == "Running":
            return True
        return raw
