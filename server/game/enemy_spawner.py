"""Random encounter rolls for overworld zones."""

from __future__ import annotations

from game.data_loader import field_enemies, get_enemy
from game.rng import Rng
from game.world_manager import zone_at

# steps-based encounter chance (DQ1-ish feel, a bit higher for MVP testing)
FIELD_ENCOUNTER_CHANCE = 10  # out of 100 per step in field
DUNGEON_ENCOUNTER_CHANCE = 14

FIELD_TABLE = field_enemies()
# Prefer weaker foes more often
FIELD_WEIGHTS = {
    "slime": 30,
    "red_slime": 20,
    "drakee": 15,
    "ghost": 12,
    "magician": 8,
    "magidrakee": 6,
    "scorpion": 5,
    "druin": 4,
    "poltergeist": 3,
    "droll": 3,
    "drakeema": 2,
    "skeleton": 2,
}


def roll_encounter(x: int, y: int, rng: Rng | None = None) -> str | None:
    rng = rng or Rng()
    zone = zone_at(x, y)
    if zone == "town":
        return None
    if zone != "field":
        return None
    if not rng.chance(FIELD_ENCOUNTER_CHANCE, 100):
        return None
    return weighted_pick(rng)


def weighted_pick(rng: Rng) -> str:
    pool = [(eid, FIELD_WEIGHTS.get(eid, 1)) for eid in FIELD_TABLE if get_enemy(eid)]
    if not pool:
        return "slime"
    total = sum(w for _, w in pool)
    roll = rng.int(1, total)
    acc = 0
    for eid, w in pool:
        acc += w
        if roll <= acc:
            return eid
    return pool[-1][0]
