"""Server-side DQ1 1v1 combat (ported from dq1-combat mechanics)."""

from __future__ import annotations

import copy
from typing import Any

from game import formulas as F
from game.data_loader import battle_spells_at, get_enemy, get_spell
from game.item_manager import equipment_bonuses
from game.progression import apply_xp, gold_add
from game.rng import Rng

MAGIC_ACTIONS = {
    "hurt",
    "hurtmore",
    "sleep",
    "stopspell",
    "heal",
    "healmore",
}


class Battle:
    def __init__(self, hero: dict, enemy_id: str, seed: int | None = None) -> None:
        template = get_enemy(enemy_id)
        if template is None:
            raise ValueError(f"unknown enemy: {enemy_id}")

        self.rng = Rng(seed)
        self.hero = self._hero_from_character(hero)
        self.enemy = self._enemy_from_template(template)
        self.phase = "awaiting_hero"
        self.outcome = "ongoing"
        self.turn = 1
        self.events: list[dict] = []
        self.rewards: dict[str, Any] = {"xp": 0, "gold": 0, "items": []}
        self.level_report: dict | None = None

        self._emit(
            {
                "kind": "battle_start",
                "enemy": self.enemy_public(),
                "message": f"A {self.enemy['name']} draws near!",
            }
        )

    @staticmethod
    def _hero_from_character(c: dict) -> dict:
        strength = int(c.get("strength", 4))
        agility = int(c.get("agility", 4))
        bonuses = equipment_bonuses(c)
        weapon = int(c.get("weapon_power", bonuses["weapon_power"]) or 0)
        armor = int(c.get("armor_power", bonuses["armor_power"]) or 0)
        shield = int(c.get("shield_power", bonuses["shield_power"]) or 0)
        accessory = int(c.get("accessory_power", bonuses["accessory_power"]) or 0)
        level = int(c.get("level", 1))
        known = c.get("known_spells") or battle_spells_at(level)
        return {
            "id": c.get("id"),
            "name": c.get("name", "Hero"),
            "level": level,
            "experience": int(c.get("experience", 0)),
            "strength": strength,
            "agility": agility,
            "max_hp": int(c.get("max_hp", 15)),
            "max_mp": int(c.get("max_mp", 0)),
            "hp": int(c.get("current_hp", c.get("max_hp", 15))),
            "mp": int(c.get("current_mp", c.get("max_mp", 0))),
            "gold": str(c.get("gold", "0")),
            "attack_power": F.hero_attack_power(strength, weapon),
            "defense_power": F.hero_defense_power(agility, armor, shield, accessory),
            "known_spells": list(known),
            "status": {"sleep": False, "stopspell": False},
            "total_kills": int(c.get("total_kills", 0)),
        }

    def _enemy_from_template(self, t: dict) -> dict:
        max_hp = int(t["max_hp"])
        hp = F.roll_encounter_hp(max_hp, self.rng)
        return {
            "id": t["id"],
            "name": t["name"],
            "strength": int(t["strength"]),
            "agility": int(t["agility"]),
            "max_hp": max_hp,
            "hp": hp,
            "sleep_resist": int(t.get("sleep_resist", 0)),
            "stopspell_resist": int(t.get("stopspell_resist", 0)),
            "hurt_resist": int(t.get("hurt_resist", 0)),
            "dodge": int(t.get("dodge", 0)),
            "xp": int(t.get("xp", 0)),
            "gold_min": int(t.get("gold_min", 0)),
            "gold_max": int(t.get("gold_max", t.get("gold_min", 0))),
            "pattern": copy.deepcopy(t.get("pattern") or {"steps": [{"action": "attack"}]}),
            "no_critical": bool(t.get("no_critical", False)),
            "status": {"sleep": False, "stopspell": False},
        }

    def _emit(self, e: dict) -> None:
        self.events.append(e)

    def _take_batch(self) -> list[dict]:
        batch = self.events
        self.events = []
        return batch

    def hero_public(self) -> dict:
        h = self.hero
        return {
            "name": h["name"],
            "level": h["level"],
            "hp": h["hp"],
            "max_hp": h["max_hp"],
            "mp": h["mp"],
            "max_mp": h["max_mp"],
            "status": dict(h["status"]),
            "known_spells": list(h["known_spells"]),
        }

    def enemy_public(self) -> dict:
        e = self.enemy
        return {
            "id": e["id"],
            "name": e["name"],
            "hp": e["hp"],
            "max_hp": e["max_hp"],
            "status": dict(e["status"]),
        }

    def snapshot(self) -> dict:
        return {
            "phase": self.phase,
            "outcome": self.outcome,
            "turn": self.turn,
            "hero": self.hero_public(),
            "enemy": self.enemy_public(),
            "legal_actions": self.legal_actions() if self.phase == "awaiting_hero" else [],
        }

    def legal_actions(self) -> list[dict]:
        if self.phase != "awaiting_hero" or self.outcome != "ongoing":
            return []
        acts: list[dict] = [{"type": "attack"}, {"type": "flee"}]
        if not self.hero["status"]["stopspell"]:
            for sid in self.hero["known_spells"]:
                sp = get_spell(sid)
                if not sp or not sp.get("battle"):
                    continue
                if self.hero["mp"] >= int(sp.get("mp_cost", 0)):
                    acts.append({"type": "spell", "id": sid})
        return acts

    def act(self, action: dict) -> dict:
        if self.outcome != "ongoing":
            return {"ok": False, "error": "battle ended", "events": [], "observe": self.snapshot()}
        if self.phase != "awaiting_hero":
            return {"ok": False, "error": "not your turn", "events": [], "observe": self.snapshot()}

        legal = self.legal_actions()
        if not self._action_legal(action, legal):
            return {"ok": False, "error": "illegal action", "events": [], "observe": self.snapshot()}

        self.phase = "resolving"
        self._emit({"kind": "turn_start", "side": "hero", "turn": self.turn})

        # hero sleep check
        if self.hero["status"]["sleep"]:
            if F.wakes_from_sleep(self.rng):
                self.hero["status"]["sleep"] = False
                self._emit({"kind": "status_woke", "target": "hero", "message": "You wake up!"})
            else:
                self._emit({"kind": "status_skip", "target": "hero", "reason": "sleep", "message": "You are still asleep!"})
                if self._check_end():
                    return self._result(True)
                self._enemy_turn()
                if self.outcome == "ongoing":
                    self.turn += 1
                    self.phase = "awaiting_hero"
                return self._result(True)

        atype = action["type"]
        if atype == "attack":
            self._hero_attack()
        elif atype == "flee":
            if self._hero_flee():
                return self._result(True)
        elif atype == "spell":
            self._hero_spell(action["id"])

        if self._check_end():
            return self._result(True)

        self._enemy_turn()
        if self.outcome == "ongoing":
            self.turn += 1
            self.phase = "awaiting_hero"
        return self._result(True)

    def _action_legal(self, action: dict, legal: list[dict]) -> bool:
        for a in legal:
            if a["type"] != action.get("type"):
                continue
            if a["type"] == "spell" and a.get("id") != action.get("id"):
                continue
            return True
        return False

    def _result(self, ok: bool, error: str | None = None) -> dict:
        return {
            "ok": ok,
            "error": error,
            "events": self._take_batch(),
            "observe": self.snapshot(),
            "rewards": self.rewards if self.outcome != "ongoing" else None,
            "level_report": self.level_report,
        }

    def _hero_attack(self) -> None:
        self._emit({"kind": "action_declared", "side": "hero", "action": "attack", "message": "You attack!"})
        res = F.hero_attack(
            self.hero["attack_power"],
            self.enemy["agility"],
            self.enemy["dodge"],
            self.rng,
            no_critical=self.enemy["no_critical"],
        )
        if res["dodged"]:
            msg = "Excellent move! But it dodged!" if res["critical"] else f"The {self.enemy['name']} dodges!"
            self._emit({"kind": "dodge", "target": "enemy", "critical": res["critical"], "message": msg})
            return
        dmg = res["damage"]
        self.enemy["hp"] = max(0, self.enemy["hp"] - dmg)
        msg = "Excellent move!" if res["critical"] else f"You hit the {self.enemy['name']} for {dmg}!"
        if res["critical"]:
            msg = f"Excellent move! {dmg} damage!"
        self._emit(
            {
                "kind": "damage",
                "target": "enemy",
                "amount": dmg,
                "critical": res["critical"],
                "source": "physical",
                "message": msg,
            }
        )

    def _hero_flee(self) -> bool:
        self._emit({"kind": "action_declared", "side": "hero", "action": "flee", "message": "You try to run..."})
        ok = F.flee_attempt(
            self.hero["agility"],
            self.enemy["agility"],
            self.rng,
            enemy_asleep=self.enemy["status"]["sleep"],
        )
        self._emit({"kind": "flee_result", "success": ok, "message": "You escaped!" if ok else "Couldn't get away!"})
        if ok:
            self.phase = "ended"
            self.outcome = "fled"
            self.rewards = {"xp": 0, "gold": 0, "items": []}
            self._emit({"kind": "battle_end", "outcome": "fled", "rewards": self.rewards})
            return True
        return False

    def _hero_spell(self, spell_id: str) -> None:
        sp = get_spell(spell_id)
        assert sp
        cost = int(sp["mp_cost"])
        self.hero["mp"] -= cost
        self._emit(
            {
                "kind": "mp_spent",
                "amount": cost,
                "mp": self.hero["mp"],
                "message": f"You cast {sp['name']}!",
            }
        )
        self._emit({"kind": "action_declared", "side": "hero", "action": "spell", "id": spell_id})

        formula = sp.get("formula") or spell_id
        if formula in ("heal", "healmore"):
            amt = F.heal_amount(self.rng) if formula == "heal" else F.healmore_amount(self.rng)
            self.hero["hp"], actual = F.apply_heal(self.hero["hp"], self.hero["max_hp"], amt)
            self._emit(
                {
                    "kind": "heal",
                    "target": "hero",
                    "amount": actual,
                    "source": formula,
                    "message": f"You recover {actual} HP!",
                }
            )
            return

        if formula in ("hurt", "hurtmore"):
            if F.resisted(self.enemy["hurt_resist"], self.rng):
                self._emit(
                    {
                        "kind": "status_resisted",
                        "target": "enemy",
                        "status": formula,
                        "message": f"The {self.enemy['name']} resists!",
                    }
                )
                return
            dmg = F.hurt_damage(self.rng) if formula == "hurt" else F.hurtmore_damage(self.rng)
            self.enemy["hp"] = max(0, self.enemy["hp"] - dmg)
            self._emit(
                {
                    "kind": "damage",
                    "target": "enemy",
                    "amount": dmg,
                    "source": formula,
                    "critical": False,
                    "message": f"{sp['name']} hits for {dmg}!",
                }
            )
            return

        if formula == "sleep":
            if F.resisted(self.enemy["sleep_resist"], self.rng):
                self._emit(
                    {
                        "kind": "status_resisted",
                        "target": "enemy",
                        "status": "sleep",
                        "message": f"The {self.enemy['name']} resists Sleep!",
                    }
                )
                return
            self.enemy["status"]["sleep"] = True
            self._emit(
                {
                    "kind": "status_applied",
                    "target": "enemy",
                    "status": "sleep",
                    "message": f"The {self.enemy['name']} is asleep!",
                }
            )
            return

        if formula == "stopspell":
            if F.resisted(self.enemy["stopspell_resist"], self.rng):
                self._emit(
                    {
                        "kind": "status_resisted",
                        "target": "enemy",
                        "status": "stopspell",
                        "message": f"The {self.enemy['name']} resists Stopspell!",
                    }
                )
                return
            self.enemy["status"]["stopspell"] = True
            self._emit(
                {
                    "kind": "status_applied",
                    "target": "enemy",
                    "status": "stopspell",
                    "message": f"The {self.enemy['name']} can't cast!",
                }
            )
            return

        self._emit({"kind": "spell_failed", "message": "The spell fizzles..."})

    def _enemy_turn(self) -> None:
        self.phase = "enemy_turn"
        self._emit({"kind": "turn_start", "side": "enemy", "turn": self.turn})

        if self.enemy["status"]["sleep"]:
            if F.wakes_from_sleep(self.rng):
                self.enemy["status"]["sleep"] = False
                self._emit(
                    {
                        "kind": "status_woke",
                        "target": "enemy",
                        "message": f"The {self.enemy['name']} wakes up!",
                    }
                )
            else:
                self._emit(
                    {
                        "kind": "status_skip",
                        "target": "enemy",
                        "reason": "sleep",
                        "message": f"The {self.enemy['name']} is sleeping.",
                    }
                )
                self._check_end()
                return

        action = self._choose_enemy_action()
        self._emit(
            {
                "kind": "enemy_action",
                "action": action,
                "message": f"The {self.enemy['name']} uses {action}!",
            }
        )
        self._resolve_enemy_action(action)
        self._check_end()

    def _choose_enemy_action(self) -> str:
        steps = (self.enemy.get("pattern") or {}).get("steps") or [{"action": "attack"}]
        ctx_hp_pct = (self.enemy["hp"] / max(1, self.enemy["max_hp"])) * 100
        for step in steps:
            action = step.get("action") or "attack"
            if action in MAGIC_ACTIONS and self.enemy["status"]["stopspell"]:
                continue
            when = step.get("when")
            if when == "hp_low" and ctx_hp_pct > 25:
                continue
            if when == "hp_high" and ctx_hp_pct < 75:
                continue
            if action == "sleep" and self.hero["status"]["sleep"]:
                continue
            if action == "stopspell" and self.hero["status"]["stopspell"]:
                continue
            if action in ("heal", "healmore") and when is None and ctx_hp_pct > 25:
                continue
            chance = step.get("chance")
            if chance is None:
                return action
            if self.rng.chance(int(chance), 100):
                return action
        return "attack"

    def _resolve_enemy_action(self, action: str) -> None:
        if action == "attack":
            res = F.enemy_attack(self.enemy["strength"], self.hero["defense_power"], self.rng)
            if res["dodged"]:
                self._emit({"kind": "dodge", "target": "hero", "message": "You dodge the attack!"})
                return
            dmg = res["damage"]
            self.hero["hp"] = max(0, self.hero["hp"] - dmg)
            self._emit(
                {
                    "kind": "damage",
                    "target": "hero",
                    "amount": dmg,
                    "source": "physical",
                    "message": f"The {self.enemy['name']} hits you for {dmg}!",
                }
            )
            return

        if action in ("hurt", "hurtmore"):
            dmg = F.hurt_damage(self.rng) if action == "hurt" else F.hurtmore_damage(self.rng)
            self.hero["hp"] = max(0, self.hero["hp"] - dmg)
            self._emit(
                {
                    "kind": "damage",
                    "target": "hero",
                    "amount": dmg,
                    "source": action,
                    "message": f"Magic hits you for {dmg}!",
                }
            )
            return

        if action in ("breath", "breath_strong"):
            dmg = F.breath_damage(self.rng, strong=action == "breath_strong")
            self.hero["hp"] = max(0, self.hero["hp"] - dmg)
            self._emit(
                {
                    "kind": "damage",
                    "target": "hero",
                    "amount": dmg,
                    "source": action,
                    "message": f"Fire breath hits for {dmg}!",
                }
            )
            return

        if action in ("heal", "healmore"):
            amt = F.enemy_heal_amount(self.rng) if action == "heal" else F.healmore_amount(self.rng)
            self.enemy["hp"], actual = F.apply_heal(self.enemy["hp"], self.enemy["max_hp"], amt)
            self._emit(
                {
                    "kind": "heal",
                    "target": "enemy",
                    "amount": actual,
                    "message": f"The {self.enemy['name']} recovers {actual} HP!",
                }
            )
            return

        if action == "sleep":
            if self.hero["status"]["sleep"]:
                return
            # hero has no sleep resist in DQ1 basically always works unless... always apply with 50%? NES uses no hero resist for sleep from enemies often
            self.hero["status"]["sleep"] = True
            self._emit(
                {
                    "kind": "status_applied",
                    "target": "hero",
                    "status": "sleep",
                    "message": "You fall asleep!",
                }
            )
            return

        if action == "stopspell":
            if self.hero["status"]["stopspell"]:
                return
            if F.hero_resists_stopspell(self.rng):
                self._emit(
                    {
                        "kind": "status_resisted",
                        "target": "hero",
                        "status": "stopspell",
                        "message": "You resist Stopspell!",
                    }
                )
                return
            self.hero["status"]["stopspell"] = True
            self._emit(
                {
                    "kind": "status_applied",
                    "target": "hero",
                    "status": "stopspell",
                    "message": "Your magic is sealed!",
                }
            )
            return

        # fallback attack
        self._resolve_enemy_action("attack")

    def _check_end(self) -> bool:
        if self.outcome != "ongoing":
            return True
        if self.hero["hp"] <= 0:
            self.phase = "ended"
            self.outcome = "defeat"
            self.rewards = {"xp": 0, "gold": 0, "items": []}
            self.hero["hp"] = 0
            self._emit({"kind": "battle_end", "outcome": "defeat", "rewards": self.rewards, "message": "You have died..."})
            return True
        if self.enemy["hp"] <= 0:
            self.phase = "ended"
            self.outcome = "victory"
            gold = self.rng.int(self.enemy["gold_min"], max(self.enemy["gold_min"], self.enemy["gold_max"]))
            self.rewards = {"xp": self.enemy["xp"], "gold": gold, "items": []}
            self.hero["total_kills"] = int(self.hero.get("total_kills", 0)) + 1
            gold_add(self.hero, gold)
            self.level_report = apply_xp(self.hero, self.enemy["xp"])
            self._emit(
                {
                    "kind": "xp_gained",
                    "amount": self.enemy["xp"],
                    "total": self.hero["experience"],
                    "message": f"You gain {self.enemy['xp']} XP!",
                }
            )
            self._emit(
                {
                    "kind": "gold_gained",
                    "amount": gold,
                    "total": self.hero["gold"],
                    "message": f"You get {gold} gold!",
                }
            )
            for up in self.level_report.get("level_ups") or []:
                self._emit(
                    {
                        "kind": "level_up",
                        "level": up["level"],
                        "stats": up,
                        "message": f"Level up! You are now level {up['level']}!",
                    }
                )
            self._emit(
                {
                    "kind": "battle_end",
                    "outcome": "victory",
                    "rewards": self.rewards,
                    "message": f"Thou hast done well in defeating the {self.enemy['name']}.",
                }
            )
            return True
        return False

    def character_patch(self) -> dict:
        """Fields to persist back to DB."""
        h = self.hero
        return {
            "level": h["level"],
            "experience": h["experience"],
            "strength": h["strength"],
            "agility": h["agility"],
            "max_hp": h["max_hp"],
            "max_mp": h["max_mp"],
            "current_hp": max(1, h["hp"]) if self.outcome == "defeat" else h["hp"],  # respawn with 1 handled outside
            "current_mp": h["mp"],
            "gold": h["gold"],
            "total_kills": h.get("total_kills", 0),
        }


class CombatEngine:
    def __init__(self) -> None:
        self.active: dict[int, Battle] = {}

    def is_in_combat(self, character_id: int) -> bool:
        return character_id in self.active

    def get(self, character_id: int) -> Battle | None:
        return self.active.get(character_id)

    def start(self, character_id: int, hero: dict, enemy_id: str, seed: int | None = None) -> Battle:
        battle = Battle(hero, enemy_id, seed=seed)
        self.active[character_id] = battle
        return battle

    def end(self, character_id: int) -> Battle | None:
        return self.active.pop(character_id, None)


combat_engine = CombatEngine()
