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

import logging
import random
from enum import Enum

logger = logging.getLogger(__name__)


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


def unimplemented_fault_modes(topology) -> list[tuple[str, str]]:
    """(equipment type, fault id) for each fault topology.yaml declares that
    the simulator has no code for. Such a mode never appears in /fault-modes;
    tests/test_simulator_fault_modes.py fails on any."""
    known = {m.value for m in FaultMode}
    return [
        (eq_type.name, fault.id)
        for eq_type in topology.equipment_types
        for fault in eq_type.fault_modes
        if fault.id not in known
    ]


def _build_type_fault_modes(topology) -> dict[str, list[FaultMode]]:
    for type_name, fault_id in unimplemented_fault_modes(topology):
        logger.warning(
            "topology.yaml declares fault mode %r for %s but the simulator has no "
            "code for it (simulator/faults.py); it won't be offered",
            fault_id,
            type_name,
        )
    known = {m.value for m in FaultMode}
    return {
        # keyed by wire-format type name, e.g. "Pump"
        eq_type.name: [FaultMode.NORMAL]
        + [FaultMode(f.id) for f in eq_type.fault_modes if f.id in known]
        for eq_type in topology.equipment_types
    }


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
        if self.mode is FaultMode.NORMAL:
            return raw
        return getattr(self, _HANDLERS[self.mode])(attr, raw)

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


# FaultState method that transforms each attribute's value, per mode. A new
# mode needs a FaultMode member, an entry here, the method, and a tick()
# case if it ramps; tests/test_simulator_fault_modes.py checks they agree.
_HANDLERS: dict[FaultMode, str] = {
    FaultMode.SUCTION_STARVATION: "_starvation",
    FaultMode.RUN_STATUS_FAULT: "_run_status",
    FaultMode.PRESSURE_DRIFT: "_pressure_drift",
    FaultMode.CAVITATION: "_cavitation",
    FaultMode.LEVEL_SENSOR_FAULT: "_level_sensor",
    FaultMode.TURBIDITY_SPIKE: "_turbidity_spike",
    FaultMode.DOSING_BLOCKAGE: "_dosing_blockage",
    FaultMode.TANK_EMPTY: "_tank_empty",
    FaultMode.LAMP_DEGRADATION: "_lamp_degradation",
    FaultMode.LAMP_FAILURE: "_lamp_failure",
}
