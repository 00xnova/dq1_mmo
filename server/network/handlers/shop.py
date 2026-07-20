"""Town shop: catalog · buy · sell (extracted).

Multiplayer reliability: combat-gated, town presence required, bad qty before
DB write, bag-full tips, mark_active + publish_status so AFK peers clear.
Self echo includes online/nearby census for room orientation.
"""

from __future__ import annotations

from typing import Any

from database.db import db_write
from game.combat_engine import combat_engine
from game.item_manager import buy_item, sell_item, shop_catalog
from game.player_manager import get_character
from game.world_manager import zone_at
from network.handlers._common import _inventory_msg, _parse_positive_qty, _resolve_item_arg
from network.protocol import ClientMessageType, ServerMessageType, msg
from network.websocket_manager import manager

SHOP_LIST_TYPES = frozenset(
    {ClientMessageType.SHOP, "shop", "store", "vendor"}
)
BUY_TYPES = frozenset({ClientMessageType.BUY, "buy", "purchase"})
SELL_TYPES = frozenset({ClientMessageType.SELL, "sell", "vendor_sell"})
ALL_TYPES = SHOP_LIST_TYPES | BUY_TYPES | SELL_TYPES


def _qty_from_data(data: dict[str, Any]) -> Any:
    if "quantity" in data:
        return data.get("quantity")
    if "qty" in data:
        return data.get("qty")
    return 1


async def handle(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None] | None:
    """Dispatch shop/buy/sell. Returns None if not a shop message."""
    msg_type = data.get("type")
    if msg_type not in ALL_TYPES:
        return None

    if character_id is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
        return character_id, user_id, outbound, None

    if combat_engine.is_in_combat(character_id):
        outbound.append(msg(ServerMessageType.ERROR, reason="in combat"))
        return character_id, user_id, outbound, None

    meta = manager.get_meta(character_id)
    # Require live presence + town (missing meta must not skip the town check)
    if not meta or zone_at(int(meta["x"]), int(meta["y"])) != "town":
        outbound.append(msg(ServerMessageType.ERROR, reason="shop only in town"))
        return character_id, user_id, outbound, None

    if msg_type in SHOP_LIST_TYPES:
        manager.touch(character_id)
        shop_msg = msg(ServerMessageType.SHOP_LIST, items=shop_catalog())
        shop_msg["online"] = len(manager.online_ids())
        shop_msg["nearby_count"] = len(manager.ids_nearby(character_id))
        shop_msg["zone"] = "town"
        shop_msg["message"] = "Town shop open."
        outbound.append(shop_msg)
        return character_id, user_id, outbound, None

    # buy / sell share item + qty validation before DB
    item_raw = data.get("item") or data.get("item_id")
    item_id, item_err = _resolve_item_arg(item_raw)
    if item_err or not item_id:
        outbound.append(
            msg(ServerMessageType.ERROR, reason=item_err or "item required")
        )
        return character_id, user_id, outbound, None
    # quantity: never use `or 1` — qty=0 must not buy/sell one unit
    qty = _parse_positive_qty(_qty_from_data(data))
    if qty is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="bad quantity"))
        return character_id, user_id, outbound, None

    char = await get_character(character_id)
    if not char:
        outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
        return character_id, user_id, outbound, None

    if msg_type in BUY_TYPES:
        async with db_write() as db:
            ok, reason, bought = await buy_item(
                db, char, str(item_id).strip(), quantity=qty
            )
        if not ok:
            err = msg(ServerMessageType.ERROR, reason=reason)
            if bought.get("cost") is not None:
                err["cost"] = bought["cost"]
            if bought.get("gold") is not None:
                err["gold"] = bought["gold"]
            if reason in ("stack full", "inventory full"):
                try:
                    inv_snap = await _inventory_msg(character_id)
                    if inv_snap.get("bag"):
                        err["bag"] = inv_snap["bag"]
                except Exception:
                    pass
            outbound.append(err)
            return character_id, user_id, outbound, None
        was_afk = manager.mark_active(character_id)
        if was_afk:
            await manager.publish_status(character_id, pulse_online=True)
        inv = await _inventory_msg(character_id)
        if bought:
            inv["bought"] = bought
            q = int(bought.get("quantity") or 1)
            inv["message"] = (
                f"Bought {q}× {bought.get('item_name') or item_id} "
                f"for {bought.get('gold_spent', 0)} G"
                if q > 1
                else f"Bought {bought.get('item_name') or item_id} for {bought.get('gold_spent', 0)} G"
            )
        inv["online"] = len(manager.online_ids())
        inv["nearby_count"] = len(manager.ids_nearby(character_id))
        inv["zone"] = "town"
        outbound.append(inv)
        return character_id, user_id, outbound, None

    # sell
    async with db_write() as db:
        ok, reason, sold = await sell_item(
            db, char, str(item_id).strip(), quantity=qty
        )
    if not ok:
        outbound.append(msg(ServerMessageType.ERROR, reason=reason))
        return character_id, user_id, outbound, None
    was_afk = manager.mark_active(character_id)
    if was_afk:
        await manager.publish_status(character_id, pulse_online=True)
    inv = await _inventory_msg(character_id)
    if sold:
        inv["sold"] = sold
        q = int(sold.get("quantity") or 1)
        inv["message"] = (
            f"Sold {q}× {sold.get('item_name') or item_id} "
            f"for {sold.get('gold_gained', 0)} G"
            if q > 1
            else f"Sold {sold.get('item_name') or item_id} for {sold.get('gold_gained', 0)} G"
        )
    inv["online"] = len(manager.online_ids())
    inv["nearby_count"] = len(manager.ids_nearby(character_id))
    inv["zone"] = "town"
    outbound.append(inv)
    return character_id, user_id, outbound, None
