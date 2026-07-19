"""XP / level-up using dq1 level table."""

from __future__ import annotations

from game.data_loader import battle_spells_at, get_level_row


def level_for_xp(xp: int) -> int:
    level = 1
    for lv in range(1, 31):
        row = get_level_row(lv)
        if not row:
            break
        if xp >= int(row["total_xp"]):
            level = lv
        else:
            break
    return level


def apply_xp(hero: dict, xp_gain: int) -> dict:
    """Mutate hero with XP; return report with level_ups list."""
    old_level = int(hero.get("level", 1))
    hero["experience"] = int(hero.get("experience", 0)) + int(xp_gain)
    new_level = level_for_xp(hero["experience"])
    report = {
        "xp_gained": int(xp_gain),
        "xp_total": hero["experience"],
        "level_ups": [],
        "new_spells": [],
    }
    if new_level > old_level:
        for lv in range(old_level + 1, new_level + 1):
            row = get_level_row(lv)
            if not row:
                continue
            up = {
                "level": lv,
                "strength": row["strength"],
                "agility": row["agility"],
                "max_hp": row["max_hp"],
                "max_mp": row["max_mp"],
                "spell": row.get("spell"),
            }
            hero["level"] = lv
            hero["strength"] = row["strength"]
            hero["agility"] = row["agility"]
            # keep current hp/mp ratio feel: full heal on level up (DQ1 style-ish)
            hero["max_hp"] = row["max_hp"]
            hero["max_mp"] = row["max_mp"]
            hero["current_hp"] = row["max_hp"]
            hero["current_mp"] = row["max_mp"]
            if row.get("spell"):
                report["new_spells"].append(row["spell"])
            report["level_ups"].append(up)
    hero["known_spells"] = battle_spells_at(int(hero["level"]))
    return report


def gold_add(hero: dict, amount: int) -> int:
    cur = int(str(hero.get("gold", "0")))
    cur += int(amount)
    hero["gold"] = str(cur)
    return amount
