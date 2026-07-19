"""Lightweight self peeks: gold · vitals · xp · spells · buffs (extracted).

Rate-exempt multiplayer helpers used under peek spam. Include zone / combat /
nearby context so players stay oriented without opening full /status.
"""

from __future__ import annotations

import time
from typing import Any

from game.combat_engine import combat_engine
from game.data_loader import battle_spells_at, field_spells_at
from game.player_manager import get_character
from game.progression import xp_to_next_level
from game.world_manager import zone_at
from network.protocol import msg
from network.websocket_manager import _is_idle, manager

GOLD_TYPES = frozenset({"gold", "money", "wallet"})
VITALS_TYPES = frozenset({"hp", "mp", "vitals", "life"})
XP_TYPES = frozenset({"xp", "exp", "level", "experience"})
SPELLS_TYPES = frozenset({"spells", "magic", "spell_list"})
BUFFS_TYPES = frozenset({"buffs", "effects", "debuffs", "status_effects"})

ALL_TYPES = GOLD_TYPES | VITALS_TYPES | XP_TYPES | SPELLS_TYPES | BUFFS_TYPES


def _zone_of_meta(meta: dict[str, Any] | None) -> str | None:
    if not meta:
        return None
    try:
        z = zone_at(int(meta["x"]), int(meta["y"]))
        return z if z in ("town", "field", "dungeon") else None
    except Exception:
        return None


async def handle(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None] | None:
    """Dispatch gold/vitals/xp/spells/buffs. Returns None if not a self peek."""
    msg_type = data.get("type")
    if msg_type not in ALL_TYPES:
        return None

    from network.protocol import ServerMessageType

    if character_id is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
        return character_id, user_id, outbound, None
    manager.touch(character_id)
    meta = manager.get_meta(character_id)
    zone = _zone_of_meta(meta)
    online_n = len(manager.online_ids())
    nearby_n = len(manager.ids_nearby(character_id))
    in_combat = combat_engine.is_in_combat(character_id)

    if msg_type in GOLD_TYPES:
        char = await get_character(character_id)
        if not char:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            return character_id, user_id, outbound, None
        gold = char.get("gold")
        zone_bit = f" · {zone}" if zone else ""
        fight_bit = " · fighting" if in_combat else ""
        outbound.append(
            msg(
                "gold",
                gold=gold,
                zone=zone,
                in_combat=in_combat,
                online=online_n,
                nearby_count=nearby_n,
                message=f"You have {gold} G{zone_bit}{fight_bit}.",
            )
        )
        return character_id, user_id, outbound, None

    if msg_type in VITALS_TYPES:
        char = await get_character(character_id)
        if not char:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            return character_id, user_id, outbound, None
        battle = combat_engine.get(character_id)
        if battle is not None and battle.outcome == "ongoing":
            chp = int(battle.hero.get("hp") or 0)
            cmp_ = int(battle.hero.get("mp") or 0)
            mhp = int(battle.hero.get("max_hp") or char.get("max_hp") or 0)
            mmp = int(battle.hero.get("max_mp") or char.get("max_mp") or 0)
        else:
            chp = int(char.get("current_hp") or 0)
            cmp_ = int(char.get("current_mp") or 0)
            mhp = int(char.get("max_hp") or 0)
            mmp = int(char.get("max_mp") or 0)
        zone_bit = f" · {zone}" if zone else ""
        fight_bit = " · fighting" if in_combat else ""
        near_bit = f" · {nearby_n} nearby" if nearby_n else ""
        outbound.append(
            msg(
                "vitals",
                hp=chp,
                max_hp=mhp,
                mp=cmp_,
                max_mp=mmp,
                in_combat=in_combat,
                zone=zone,
                online=online_n,
                nearby_count=nearby_n,
                message=f"HP {chp}/{mhp} · MP {cmp_}/{mmp}{zone_bit}{fight_bit}{near_bit}",
            )
        )
        return character_id, user_id, outbound, None

    if msg_type in XP_TYPES:
        char = await get_character(character_id)
        if not char:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            return character_id, user_id, outbound, None
        lvl = int(char.get("level") or 1)
        xp = int(char.get("experience") or 0)
        xp_prog = xp_to_next_level(xp, lvl)
        to_next = xp_prog.get("xp_to_next")
        zone_bit = f" · {zone}" if zone else ""
        near_bit = f" · {nearby_n} nearby" if nearby_n else ""
        base = f"Level {lvl} · {xp} XP"
        if to_next is not None and not xp_prog.get("max_level"):
            base += f" · {to_next} to next"
        outbound.append(
            msg(
                "xp",
                level=lvl,
                experience=xp,
                xp_progress=xp_prog,
                zone=zone,
                online=online_n,
                nearby_count=nearby_n,
                in_combat=in_combat,
                message=base + zone_bit + near_bit,
            )
        )
        return character_id, user_id, outbound, None

    if msg_type in SPELLS_TYPES:
        char = await get_character(character_id)
        if not char:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            return character_id, user_id, outbound, None
        lvl = int(char.get("level") or 1)
        battle = battle_spells_at(lvl)
        field = field_spells_at(lvl)
        zone_bit = f" · {zone}" if zone else ""
        outbound.append(
            msg(
                "spells",
                battle=battle,
                field=field,
                level=lvl,
                zone=zone,
                in_combat=in_combat,
                message=(
                    f"Battle: {', '.join(battle) or 'none'} · "
                    f"Field: {', '.join(field) or 'none'}{zone_bit}"
                ),
            )
        )
        return character_id, user_id, outbound, None

    if msg_type in BUFFS_TYPES:
        repel = manager.repel_remaining(character_id)
        radiant = manager.radiant_remaining(character_id)
        afk = bool(meta.get("afk")) if meta else False
        idle = _is_idle(meta) if meta else False
        afk_for = None
        if afk and meta is not None:
            try:
                since = float(meta.get("afk_since") or 0.0)
                if since > 0:
                    afk_for = max(0, int(time.monotonic() - since))
            except (TypeError, ValueError):
                afk_for = None
        bits: list[str] = []
        if repel > 0:
            bits.append(f"Repel {repel}")
        if radiant > 0:
            bits.append(f"Radiant {radiant}")
        if in_combat:
            bits.append("In combat")
        afk_reason = None
        if afk and meta is not None:
            am = meta.get("afk_message")
            if isinstance(am, str) and am.strip():
                afk_reason = am.strip()[:48]
        if afk:
            if afk_reason:
                bits.append(
                    f"AFK ({afk_reason})"
                    + (f" {afk_for}s" if afk_for is not None else "")
                )
            else:
                bits.append(f"AFK {afk_for}s" if afk_for is not None else "AFK")
        elif idle:
            bits.append("Idle")
        # Keep "No active buffs." when empty so clients/tests can detect clean state
        if bits:
            if nearby_n:
                bits.append(f"{nearby_n} nearby")
            if zone:
                bits.append(str(zone))
            buff_msg = " · ".join(bits)
        else:
            buff_msg = "No active buffs."
            if zone:
                buff_msg += f" · {zone}"
        body: dict[str, Any] = {
            "type": "buffs",
            "repel": repel,
            "radiant": radiant,
            "in_combat": in_combat,
            "afk": afk,
            "idle": idle,
            "zone": zone,
            "online": online_n,
            "nearby_count": nearby_n,
            "session_id": manager.session_id(character_id),
            "message": buff_msg,
        }
        if afk_for is not None:
            body["afk_for"] = afk_for
        if afk_reason:
            body["afk_message"] = afk_reason
        outbound.append(body)
        return character_id, user_id, outbound, None

    return None
