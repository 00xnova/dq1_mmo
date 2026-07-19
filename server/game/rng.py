"""Seeded RNG matching dq1combat.Rng (byte 0-255, chance n/d)."""

from __future__ import annotations

import random


class Rng:
    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)

    def byte(self) -> int:
        return self._rng.randint(0, 255)

    def chance(self, n: int, d: int) -> bool:
        if d <= 0 or n <= 0:
            return False
        if n >= d:
            return True
        return self._rng.randint(1, d) <= n

    def int(self, lo: int, hi: int) -> int:
        if hi < lo:
            lo, hi = hi, lo
        return self._rng.randint(lo, hi)

    def choice(self, seq):
        return self._rng.choice(seq)
