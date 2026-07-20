"""Bag · equip · unequip · discard (extracted).

Multiplayer reliability: combat-gated mutations, safe qty for discard,
mark_active + publish_status on successful equip/unequip/discard so AFK
peers update. Bag peek is rate-exempt touch with room census.
"""

from __future__ import annotations

from typing import Any

from database.db import db_write
from game.combat_engine import combat_engine
from game.item_manager import (
    SLOT_COLUMNS,
    discard_item,
    equip_item,
    get_equipment_def,
    unequip_item,
)
from game.player_manager import get_character
from game.world_manager import zone_at
from network.handlers._common import (
    _inventory_msg,
    _parse_positive_qty,
    _resolve_item_arg,
)
from network.protocol import ClientMessageType, ServerMessageType, msg
from network.websocket_manager import manager

BAG_TYPES = frozenset(
    {ClientMessageType.INVENTORY, "inventory", "bag", "inv", "items"}
)
EQUIP_TYPES = frozenset({ClientMessageType.EQUIP, "equip", "wear", "wield"})
UNEQUIP_TYPES = frozenset(
    {ClientMessageType.UNEQUIP, "unequip", "takeoff", "remove"}
)
DISCARD_TYPES = frozenset({"discard", "drop", "destroy", "throw_away"})
ALL_TYPES = BAG_TYPES | EQUIP_TYPES | UNEQUIP_TYPES | DISCARD_TYPES


def _census(character_id: int, inv: dict[str, Any]) -> dict[str, Any]:
    inv["online"] = len(manager.online_ids())
    inv["nearby_count"] = len(manager.ids_nearby(character_id))
    meta = manager.get_meta(character_id)
    if meta is not None:
        try:
            z = zone_at(int(meta["x"]), int(meta["y"]))
            if z in ("town", "field", "dungeon"):
                inv["zone"] = z
        except Exception:
            pass
    return inv


async def handle(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None] | None:
    """Dispatch bag/equip/unequip/discard. Returns None if not inventory."""
    msg_type = data.get("type")
    if msg_type not in ALL_TYPES:
        return None

    if character_id is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
        return character_id, user_id, outbound, None

    # --- Bag peek (rate-exempt touch) ---
    if msg_type in BAG_TYPES:
        manager.touch(character_id)
        inv = await _inventory_msg(character_id)
        outbound.append(_census(character_id, inv))
        return character_id, user_id, outbound, None

    # Mutations blocked mid-fight
    if combat_engine.is_in_combat(character_id):
        outbound.append(msg(ServerMessageType.ERROR, reason="in combat"))
        return character_id, user_id, outbound, None

    if msg_type in EQUIP_TYPES:
        slot = data.get("slot")
        item_raw = data.get("item") or data.get("item_id")
        item_id, item_err = (
            _resolve_item_arg(item_raw) if item_raw else (None, "item required")
        )
        if item_err or not item_id:
            outbound.append(
                msg(ServerMessageType.ERROR, reason=item_err or "item required")
            )
            return character_id, user_id, outbound, None
        # Auto-slot from equipment def when client only sends item (slash /equip club)
        if (not slot or not str(slot).strip()) and item_id:
            defn = get_equipment_def(str(item_id).strip())
            if defn and defn.get("slot"):
                slot = defn.get("slot")
        char = await get_character(character_id)
        if not char:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            return character_id, user_id, outbound, None
        async with db_write() as db:
            ok, reason = await equip_item(
                db, char, str(slot or ""), str(item_id or "")
            )
        if not ok:
            outbound.append(msg(ServerMessageType.ERROR, reason=reason))
            return character_id, user_id, outbound, None
        was_afk = manager.mark_active(character_id)
        if was_afk:
            await manager.publish_status(character_id, pulse_online=True)
        inv = await _inventory_msg(character_id)
        inv["equipped"] = {"slot": str(slot or ""), "item_id": str(item_id or "")}
        inv["message"] = f"Equipped {item_id}."
        outbound.append(_census(character_id, inv))
        return character_id, user_id, outbound, None

    if msg_type in UNEQUIP_TYPES:
        slot = data.get("slot")
        char = await get_character(character_id)
        if not char:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            return character_id, user_id, outbound, None
        # Remember what was equipped for the toast (unequip mutates char)
        prev_id = None
        slot_s = str(slot or "")
        col = SLOT_COLUMNS.get(slot_s)
        if col:
            prev_id = char.get(col)
        async with db_write() as db:
            ok, reason = await unequip_item(db, char, slot_s)
        if not ok:
            outbound.append(msg(ServerMessageType.ERROR, reason=reason))
            return character_id, user_id, outbound, None
        was_afk = manager.mark_active(character_id)
        if was_afk:
            await manager.publish_status(character_id, pulse_online=True)
        inv = await _inventory_msg(character_id)
        inv["unequipped"] = {"slot": slot_s, "item_id": prev_id}
        inv["message"] = (
            f"Unequipped {prev_id}." if prev_id else f"Unequipped {slot_s}."
        )
        outbound.append(_census(character_id, inv))
        return character_id, user_id, outbound, None

    # discard / drop
    item_raw = data.get("item") or data.get("item_id")
    item_id, item_err = _resolve_item_arg(item_raw)
    if item_err or not item_id:
        outbound.append(
            msg(ServerMessageType.ERROR, reason=item_err or "item required")
        )
        return character_id, user_id, outbound, None
    # Explicit quantity parse — do not use `or 1` (qty=0 must not discard one)
    if "quantity" in data:
        raw_qty = data.get("quantity")
    elif "qty" in data:
        raw_qty = data.get("qty")
    else:
        raw_qty = 1
    qty = _parse_positive_qty(raw_qty)
    if qty is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="bad quantity"))
        return character_id, user_id, outbound, None
    char = await get_character(character_id)
    if not char:
        outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
        return character_id, user_id, outbound, None
    async with db_write() as db:
        ok, reason, info = await discard_item(db, char, str(item_id), qty)
    if not ok:
        outbound.append(msg(ServerMessageType.ERROR, reason=reason))
        return character_id, user_id, outbound, None
    was_afk = manager.mark_active(character_id)
    if was_afk:
        await manager.publish_status(character_id, pulse_online=True)
    inv = await _inventory_msg(character_id)
    inv["discarded"] = info
    inv["message"] = (
        f"Discarded {info.get('quantity', 1)}× "
        f"{info.get('item_name') or item_id}"
    )
    outbound.append(_census(character_id, inv))
    return character_id, user_id, outbound, None
