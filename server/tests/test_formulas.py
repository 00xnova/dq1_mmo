"""Unit tests for DQ1 formulas (deterministic seeds)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game.formulas import (
    flee_attempt,
    hero_attack,
    hero_attack_power,
    hero_defense_power,
    hurt_damage,
    normal_damage,
)
from game.rng import Rng


def test_attack_defense_power():
    assert hero_attack_power(4, 10) == 14
    assert hero_defense_power(10, 4, 4, 2) == 5 + 4 + 4 + 2


def test_normal_damage_range():
    rng = Rng(1)
    samples = [normal_damage(20, 6, rng) for _ in range(50)]
    assert min(samples) >= 0
    assert max(samples) <= 20


def test_hero_attack_deterministic():
    a = hero_attack(14, 3, 1, Rng(99))
    b = hero_attack(14, 3, 1, Rng(99))
    assert a == b


def test_hurt_band():
    rng = Rng(0)
    vals = {hurt_damage(rng) for _ in range(200)}
    assert min(vals) >= 5
    assert max(vals) <= 12


def test_flee_asleep_always():
    assert flee_attempt(1, 99, Rng(1), enemy_asleep=True) is True
