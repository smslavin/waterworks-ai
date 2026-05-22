"""Value generators for the WTP simulator."""

import random


class RandomWalk:
    def __init__(self, initial: float, lo: float, hi: float, step: float):
        self.value = float(initial)
        self.lo = float(lo)
        self.hi = float(hi)
        self.step = float(step)

    def next(self) -> float:
        self.value += random.uniform(-self.step, self.step)
        self.value = max(self.lo, min(self.hi, self.value))
        return round(self.value, 2)


class OscillatingBool:
    def __init__(self, initial: bool, flip_chance: float = 0.01):
        self.value = initial
        self.flip_chance = flip_chance

    def next(self) -> bool:
        if random.random() < self.flip_chance:
            self.value = not self.value
        return self.value


def rw(lo: float, hi: float, step: float | None = None) -> RandomWalk:
    mid = (lo + hi) / 2
    return RandomWalk(
        mid + random.uniform(-(hi - lo) * 0.1, (hi - lo) * 0.1),
        lo, hi,
        step if step is not None else (hi - lo) * 0.01,
    )


def ob(initial: bool = True, flip: float = 0.01) -> OscillatingBool:
    return OscillatingBool(initial, flip)
