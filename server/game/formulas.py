"""DQ1 combat formulas ported from dq1combat."""

from __future__ import annotations

from game.rng import Rng


def hero_attack_power(strength: int, weapon_power: int = 0) -> int:
    return int(strength) + int(weapon_power)


def hero_defense_power(agility: int, armor: int = 0, shield: int = 0, accessory: int = 0) -> int:
    return (int(agility) // 2) + int(armor) + int(shield) + int(accessory)


def roll_critical(rng: Rng) -> bool:
    return rng.chance(1, 32)


def hero_dodges(rng: Rng) -> bool:
    return rng.chance(1, 32)


def enemy_dodges(dodge_out_of_64: int, rng: Rng) -> bool:
    return rng.chance(int(dodge_out_of_64 or 0), 64)


def critical_damage(attack_power: int, rng: Rng) -> int:
    attack_power = int(attack_power)
    if attack_power <= 0:
        return 0
    half = attack_power // 2
    r = rng.byte()
    dmg = attack_power - ((r * half) // 256)
    return max(1, dmg)


def normal_damage(attack_power: int, defense_power: int, rng: Rng) -> int:
    base = int(attack_power) - (int(defense_power) // 2)
    if base <= 0:
        return 0
    r = rng.byte()
    return ((r + 256) * base) // 1024


def resolve_minimum_damage(dmg: int, rng: Rng) -> tuple[int, bool]:
    if dmg >= 1:
        return dmg, False
    if rng.chance(1, 2):
        return 1, True
    return 0, True


def hero_attack(
    hero_atk: int,
    enemy_agi: int,
    enemy_dodge: int,
    rng: Rng,
    *,
    no_critical: bool = False,
) -> dict:
    result = {"damage": 0, "critical": False, "dodged": False, "min_roll": False}
    if enemy_dodges(enemy_dodge, rng):
        result["dodged"] = True
        if not no_critical and roll_critical(rng):
            result["critical"] = True
        return result
    if not no_critical and roll_critical(rng):
        result["critical"] = True
        result["damage"] = critical_damage(hero_atk, rng)
        return result
    dmg = normal_damage(hero_atk, enemy_agi, rng)
    dmg, result["min_roll"] = resolve_minimum_damage(dmg, rng)
    result["damage"] = dmg
    return result


def weak_enemy_damage(enemy_str: int, rng: Rng) -> int:
    enemy_str = int(enemy_str)
    if enemy_str <= 0:
        return 0
    thrash = enemy_str // 2 + 1
    return (rng.byte() * thrash) // 256


def enemy_attack(enemy_str: int, hero_def: int, rng: Rng) -> dict:
    result = {"damage": 0, "dodged": False, "used_weak_formula": False}
    if hero_dodges(rng):
        result["dodged"] = True
        return result
    enemy_str = int(enemy_str)
    hero_def = int(hero_def)
    if enemy_str <= hero_def:
        result["used_weak_formula"] = True
        result["damage"] = weak_enemy_damage(enemy_str, rng)
        return result
    dmg = normal_damage(enemy_str, hero_def, rng)
    if dmg < 1:
        dmg, _ = resolve_minimum_damage(dmg, rng)
    result["damage"] = dmg
    return result


def hurt_damage(rng: Rng) -> int:
    return (rng.byte() % 8) + 5


def hurtmore_damage(rng: Rng) -> int:
    return (rng.byte() % 8) + 58


def heal_amount(rng: Rng) -> int:
    return rng.int(10, 17)


def healmore_amount(rng: Rng) -> int:
    return rng.int(85, 100)


def enemy_heal_amount(rng: Rng) -> int:
    return rng.int(20, 27)


def breath_damage(rng: Rng, strong: bool = False) -> int:
    if strong:
        return rng.int(65, 72)
    return rng.int(16, 23)


def resisted(resist_out_of_16: int, rng: Rng) -> bool:
    return rng.chance(int(resist_out_of_16 or 0), 16)


def hero_resists_stopspell(rng: Rng) -> bool:
    return rng.chance(1, 2)


def wakes_from_sleep(rng: Rng) -> bool:
    return rng.chance(1, 2)


def apply_heal(current_hp: int, max_hp: int, amount: int) -> tuple[int, int]:
    nxt = min(int(max_hp), int(current_hp) + int(amount))
    return nxt, nxt - int(current_hp)


def flee_attempt(hero_agi: int, enemy_agi: int, rng: Rng, *, enemy_asleep: bool = False) -> bool:
    if enemy_asleep:
        return True
    r1 = rng.byte()
    r2 = rng.byte()
    enemy_factor = int(enemy_agi) * (r1 // 4)
    hero_factor = int(hero_agi) * r2
    return enemy_factor <= hero_factor


def roll_encounter_hp(max_hp: int, rng: Rng) -> int:
    # 75%–100% of max_hp
    max_hp = int(max_hp)
    lo = max(1, (max_hp * 75) // 100)
    return rng.int(lo, max_hp)
