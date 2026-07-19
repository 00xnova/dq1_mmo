"""Enemy encounter system — Phase 4."""

import random

# Placeholder encounter table (ids match dq1-combat)
ZONE_ENEMIES = {
    "field": ["slime", "red_slime", "drakee"],
    "dungeon": ["skeleton", "ghost", "magician"],
}


def roll_encounter(zone: str = "field", chance: float = 0.08) -> str | None:
    if random.random() > chance:
        return None
    table = ZONE_ENEMIES.get(zone, ZONE_ENEMIES["field"])
    return random.choice(table)
