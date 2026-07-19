"""Load shared DQ1 combat data (exported from dq1-combat)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[2] / "shared" / "dq1_data.json"


@lru_cache(maxsize=1)
def load_data() -> dict:
    with open(DATA_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    enemies = {e["id"]: e for e in raw["enemies"]}
    spells = raw["spells"]
    levels = {row["level"]: row for row in raw["levels"]}
    return {"enemies": enemies, "spells": spells, "levels": levels}


def get_enemy(enemy_id: str) -> dict | None:
    return load_data()["enemies"].get(enemy_id)


def get_spell(spell_id: str) -> dict | None:
    return load_data()["spells"].get(spell_id)


def get_level_row(level: int) -> dict | None:
    return load_data()["levels"].get(level)


def spells_known_at(level: int) -> list[str]:
    known: list[str] = []
    for lv in range(1, level + 1):
        row = get_level_row(lv)
        if row and row.get("spell"):
            known.append(row["spell"])
    return known


def battle_spells_at(level: int) -> list[str]:
    out = []
    for sid in spells_known_at(level):
        sp = get_spell(sid)
        if sp and sp.get("battle"):
            out.append(sid)
    return out


def field_enemies() -> list[str]:
    # early/mid overworld set
    ids = [
        "slime",
        "red_slime",
        "drakee",
        "ghost",
        "magician",
        "magidrakee",
        "scorpion",
        "druin",
        "poltergeist",
        "droll",
        "drakeema",
        "skeleton",
    ]
    enemies = load_data()["enemies"]
    return [i for i in ids if i in enemies]
