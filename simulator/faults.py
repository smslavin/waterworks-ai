"""Fault injection for the WTP simulator.

Each FaultState instance is attached to one process unit. Calling apply() each
tick returns the (possibly transformed) value for a given attribute. Calling
tick() advances any internal ramp or drift state once per publish cycle.

Fault modes
-----------
normal              Clean random-walk signals; no transformation applied.
suction_starvation  Pump is running but supply is cut. Flow ramps toward zero
                    over ~25 ticks, power follows, pressure becomes erratic.
                    Running stays True.
run_status_fault    Running feedback bit reads True but the pump is actually
                    off — Flow and Power read near zero. Simulates a stuck
                    discrete output or wiring fault.
pressure_drift      Reported pressure diverges progressively from true value
                    via a cumulative transmitter offset. All other attrs normal.
cavitation          Pump running with intermittent vapor formation. Flow
                    collapses unpredictably; pressure has rapid spikes/dips.
"""

import random
from enum import Enum


class FaultMode(str, Enum):
    NORMAL              = "normal"
    SUCTION_STARVATION  = "suction_starvation"
    RUN_STATUS_FAULT    = "run_status_fault"
    PRESSURE_DRIFT      = "pressure_drift"
    CAVITATION          = "cavitation"


class FaultState:
    def __init__(self) -> None:
        self.mode: FaultMode = FaultMode.NORMAL
        self._intensity: float = 0.0    # 0→1 ramp used by suction_starvation
        self._drift_offset: float = 0.0  # cumulative offset used by pressure_drift

    def set_mode(self, mode: FaultMode) -> None:
        if mode != self.mode:
            self.mode = mode
            self._intensity = 0.0
            self._drift_offset = 0.0

    def tick(self) -> None:
        """Advance internal state once per publish cycle, before apply() calls."""
        if self.mode == FaultMode.SUCTION_STARVATION:
            # ~25 ticks to reach full severity
            self._intensity = min(1.0, self._intensity + 0.04)
        elif self.mode == FaultMode.PRESSURE_DRIFT:
            self._drift_offset += random.uniform(0.05, 0.15)

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
        return raw  # unreachable, satisfies type checkers

    # ── Fault transformations ─────────────────────────────────────────────────

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
            # Erratic spikes as pump cavitates with no supply
            return round(float(raw) + random.uniform(-3.0, 3.0) * i, 2)
        return raw

    def _run_status(self, attr: str, raw: float | bool) -> float | bool:
        if attr == "Running":
            return True
        if attr in ("Flow", "Power"):
            # Pump is off — only electrical noise remains
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
            # 15% chance of a collapse event each tick
            if random.random() < 0.15:
                return round(float(raw) * random.uniform(0.0, 0.2), 2)
            return round(float(raw) * random.uniform(0.6, 1.4), 2)
        if attr == "Pressure":
            return round(float(raw) * random.uniform(0.7, 1.3), 2)
        if attr == "Power":
            return round(float(raw) * random.uniform(1.0, 1.15), 2)
        return raw
