from typing import Any

from auth.jwt_handler import decode_access_token
from config import ALLOW_DEBUG
from database.db import db_write, get_db
from game.combat_engine import combat_engine
from game.data_loader import battle_spells_at, get_enemy
from game.enemy_spawner import roll_encounter
from game.item_manager import (
    buy_item,
    character_public,
    equip_item,
    equipment_bonuses,
    list_items,
    sell_item,
    shop_catalog,
    unequip_item,
)
from game.player_manager import apply_character_patch, get_character
from game.rng import Rng
from game.serialize import character_dict
from game.world_manager import SPAWN_X, SPAWN_Y, is_adjacent_step, is_walkable, map_payload, zone_at
from network.protocol import ClientMessageType, ServerMessageType, msg
from network.websocket_manager import manager


async def _inventory_msg(character_id: int) -> dict:
    db = await get_db()
    char = await get_character(character_id)
    items = await list_items(db, character_id)
    if char:
        char["known_spells"] = battle_spells_at(int(char["level"]))
        char = character_public(char, items)
    return msg(ServerMessageType.INVENTORY_UPDATE, items=items, character=char)


async def handle_disconnect(character_id: int) -> None:
    """Persist position + any in-flight battle when a client disconnects."""
    meta = manager.get_meta(character_id)
    patch: dict = {}
    if meta is not None:
        patch["world_x"] = meta["x"]
        patch["world_y"] = meta["y"]
        manager.mark_clean(character_id)

    battle = combat_engine.get(character_id)
    if battle is not None:
        patch["current_hp"] = max(1, int(battle.hero["hp"]))
        patch["current_mp"] = max(0, int(battle.hero["mp"]))
        combat_engine.end(character_id)

    if patch:
        await apply_character_patch(character_id, patch)


def _combat_update(battle, events: list | None = None) -> dict:
    snap = battle.snapshot()
    return msg(
        ServerMessageType.COMBAT_UPDATE,
        player_hp=snap["hero"]["hp"],
        player_mp=snap["hero"]["mp"],
        player_max_hp=snap["hero"]["max_hp"],
        player_max_mp=snap["hero"]["max_mp"],
        enemy=snap["enemy"],
        events=events or [],
        legal_actions=snap["legal_actions"],
        turn=snap["turn"],
        phase=snap["phase"],
        outcome=snap["outcome"],
    )


async def _persist_battle_end(character_id: int, battle) -> dict:
    patch = battle.character_patch()
    if battle.outcome == "defeat":
        # DQ1-ish: wake at town, keep XP, lose half gold
        gold = int(str(patch.get("gold", "0")))
        gold = gold // 2
        patch["gold"] = str(gold)
        patch["current_hp"] = max(1, int(patch.get("max_hp", 15)) // 2)
        patch["world_x"] = SPAWN_X
        patch["world_y"] = SPAWN_Y
        manager.set_position(character_id, SPAWN_X, SPAWN_Y)
    char = await apply_character_patch(character_id, patch)
    if not char:
        return {}
    char["known_spells"] = battle_spells_at(int(char["level"]))
    char["bonuses"] = equipment_bonuses(char)
    return char


async def handle_message(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
) -> tuple[int | None, int | None, list[dict], dict | None]:
    msg_type = data.get("type")
    outbound: list[dict] = []
    connect_meta: dict | None = None

    if msg_type == ClientMessageType.PING:
        if character_id is not None:
            manager.touch(character_id)
        # Echo client timestamp for RTT; optional presence bundle
        client_t = data.get("t")
        outbound.append(msg(ServerMessageType.PONG, t=client_t))
        if data.get("sync") or data.get("presence"):
            if character_id is not None:
                nearby = manager.nearby_players(character_id)
                outbound.append(
                    msg(
                        ServerMessageType.WORLD_STATE,
                        players=nearby,
                        enemies=[],
                        map=map_payload(),
                    )
                )
        return character_id, user_id, outbound, None

    if msg_type == ClientMessageType.SYNC or msg_type == "sync":
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        meta = manager.get_meta(character_id)
        nearby = manager.nearby_players(character_id)
        outbound.append(
            msg(
                ServerMessageType.WORLD_STATE,
                players=nearby,
                enemies=[],
                map=map_payload(),
                you={"x": meta["x"], "y": meta["y"]} if meta else None,
            )
        )
        return character_id, user_id, outbound, None

    if msg_type == ClientMessageType.AUTH:
        token = data.get("token")
        char_id = data.get("character_id")
        if not token or not char_id:
            outbound.append(msg(ServerMessageType.AUTH_FAIL, reason="token and character_id required"))
            return character_id, user_id, outbound, None

        payload = decode_access_token(token)
        if payload is None:
            outbound.append(msg(ServerMessageType.AUTH_FAIL, reason="invalid token"))
            return character_id, user_id, outbound, None

        db = await get_db()
        async with db.execute(
            "SELECT * FROM characters WHERE id = ? AND user_id = ?",
            (int(char_id), payload["user_id"]),
        ) as c:
            row = await c.fetchone()
        if row is None:
            outbound.append(msg(ServerMessageType.AUTH_FAIL, reason="character not found"))
            return character_id, user_id, outbound, None

        character = character_dict(row)
        x = int(character["world_x"])
        y = int(character["world_y"])
        if not is_walkable(x, y):
            x, y = SPAWN_X, SPAWN_Y
            async with db_write() as wdb:
                await wdb.execute(
                    "UPDATE characters SET world_x = ?, world_y = ? WHERE id = ?",
                    (x, y, character["id"]),
                )
                await wdb.commit()
            character["world_x"] = x
            character["world_y"] = y

        # Drop stale combat if reconnecting
        if combat_engine.is_in_combat(character["id"]):
            await handle_disconnect(character["id"])

        character["known_spells"] = battle_spells_at(int(character["level"]))
        character["bonuses"] = equipment_bonuses(character)

        connect_meta = {
            "character_id": character["id"],
            "name": character["name"],
            "x": character["world_x"],
            "y": character["world_y"],
            "map_id": character["map_id"],
            "level": character["level"],
        }

        outbound.append(
            msg(
                ServerMessageType.AUTH_OK,
                player_id=character["id"],
                character=character,
                map=map_payload(),
            )
        )
        outbound.append(msg(ServerMessageType.WORLD_STATE, players=[], enemies=[], map=map_payload()))
        return character["id"], payload["user_id"], outbound, connect_meta

    if character_id is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
        return character_id, user_id, outbound, None

    # --- Combat actions ---
    if msg_type in (
        ClientMessageType.ATTACK,
        ClientMessageType.FLEE,
        ClientMessageType.USE_SPELL,
        "combat_action",
    ):
        battle = combat_engine.get(character_id)
        if battle is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="not in combat"))
            return character_id, user_id, outbound, None

        if msg_type == ClientMessageType.ATTACK or (
            msg_type == "combat_action" and data.get("action") == "attack"
        ):
            action = {"type": "attack"}
        elif msg_type == ClientMessageType.FLEE or (
            msg_type == "combat_action" and data.get("action") == "flee"
        ):
            action = {"type": "flee"}
        else:
            spell = data.get("spell") or data.get("id")
            if msg_type == "combat_action":
                spell = data.get("spell") or data.get("id")
                if data.get("action") == "spell":
                    action = {"type": "spell", "id": spell}
                else:
                    action = {"type": data.get("action"), "id": spell}
            else:
                action = {"type": "spell", "id": spell}

        # Only accept actions while awaiting hero input (blocks spam mid-resolve)
        if battle.phase != "awaiting_hero" or battle.outcome != "ongoing":
            outbound.append(msg(ServerMessageType.ERROR, reason="wait for your turn"))
            outbound.append(_combat_update(battle, []))
            return character_id, user_id, outbound, None

        result = battle.act(action)
        if not result["ok"]:
            outbound.append(msg(ServerMessageType.ERROR, reason=result.get("error") or "bad action"))
            outbound.append(_combat_update(battle, []))
            return character_id, user_id, outbound, None

        events = result["events"]
        outbound.append(_combat_update(battle, events))

        for e in events:
            if e.get("kind") == "level_up":
                outbound.append(
                    msg(
                        ServerMessageType.LEVEL_UP,
                        new_level=e.get("level"),
                        new_stats=e.get("stats"),
                    )
                )

        if battle.outcome != "ongoing":
            char = await _persist_battle_end(character_id, battle)
            combat_engine.end(character_id)
            outbound.append(
                msg(
                    ServerMessageType.COMBAT_END,
                    result=battle.outcome,
                    xp=(battle.rewards or {}).get("xp", 0),
                    gold=(battle.rewards or {}).get("gold", 0),
                    character=char,
                    events=events,
                )
            )
            if battle.outcome == "defeat":
                outbound.append(
                    msg(
                        ServerMessageType.PLAYER_MOVED,
                        player_id=character_id,
                        x=SPAWN_X,
                        y=SPAWN_Y,
                    )
                )
        return character_id, user_id, outbound, None

    # --- Movement (server-authoritative, ack'd, rate-limited, DB-deferred) ---
    if msg_type == ClientMessageType.MOVE:
        seq = data.get("seq")
        if isinstance(seq, float):
            seq = int(seq)
        if not isinstance(seq, int):
            seq = None

        def _reject(reason: str, mx: int, my: int) -> None:
            outbound.append(
                msg(
                    ServerMessageType.ERROR,
                    reason=reason,
                    x=mx,
                    y=my,
                    seq=seq,
                )
            )
            # Always ack so client can reconcile
            outbound.append(msg(ServerMessageType.MOVE_OK, ok=False, x=mx, y=my, seq=seq, reason=reason))

        if combat_engine.is_in_combat(character_id):
            meta = manager.get_meta(character_id)
            mx = int(meta["x"]) if meta else 0
            my = int(meta["y"]) if meta else 0
            _reject("in combat", mx, my)
            return character_id, user_id, outbound, None

        x = data.get("x")
        y = data.get("y")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            meta = manager.get_meta(character_id)
            mx = int(meta["x"]) if meta else 0
            my = int(meta["y"]) if meta else 0
            _reject("invalid move", mx, my)
            return character_id, user_id, outbound, None

        tx, ty = int(x), int(y)
        meta = manager.get_meta(character_id)
        if meta is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="not connected"))
            return character_id, user_id, outbound, None

        fx, fy = int(meta["x"]), int(meta["y"])

        # Duplicate / old seq: ignore but confirm current pos (idempotent)
        last_seq = int(meta.get("last_move_seq") or 0)
        if seq is not None and seq <= last_seq:
            outbound.append(
                msg(ServerMessageType.MOVE_OK, ok=True, x=fx, y=fy, seq=seq, duplicate=True)
            )
            return character_id, user_id, outbound, None

        allowed, retry = manager.allow_move(character_id)
        if not allowed:
            outbound.append(
                msg(
                    ServerMessageType.MOVE_OK,
                    ok=False,
                    x=fx,
                    y=fy,
                    seq=seq,
                    reason="rate_limit",
                    retry_after=round(retry, 3),
                )
            )
            return character_id, user_id, outbound, None

        if not is_adjacent_step(fx, fy, tx, ty):
            _reject("invalid step", fx, fy)
            return character_id, user_id, outbound, None

        if not is_walkable(tx, ty):
            _reject("blocked", fx, fy)
            return character_id, user_id, outbound, None

        # Apply in memory; background task flushes to SQLite
        manager.set_position(character_id, tx, ty, seq=seq)

        outbound.append(msg(ServerMessageType.MOVE_OK, ok=True, x=tx, y=ty, seq=seq))
        move_msg = msg(
            ServerMessageType.PLAYER_MOVED,
            player_id=character_id,
            x=tx,
            y=ty,
            seq=seq,
        )
        await manager.broadcast_nearby(character_id, move_msg, include_self=False)

        # Random encounter
        enemy_id = roll_encounter(tx, ty, Rng())
        if enemy_id:
            # Force position flush before combat so reconnect is consistent
            async with db_write() as db:
                await db.execute(
                    "UPDATE characters SET world_x = ?, world_y = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (tx, ty, character_id),
                )
                await db.commit()
            manager.mark_clean(character_id)

            char = await get_character(character_id)
            if char:
                char["known_spells"] = battle_spells_at(int(char["level"]))
                battle = combat_engine.start(character_id, char, enemy_id)
                start_events = battle._take_batch()
                outbound.append(
                    msg(
                        ServerMessageType.COMBAT_START,
                        enemy=battle.enemy_public(),
                        hero=battle.hero_public(),
                        legal_actions=battle.legal_actions(),
                        events=start_events,
                    )
                )
                outbound.append(_combat_update(battle, start_events))

        return character_id, user_id, outbound, None

    # --- Inventory / shop / equip ---
    if msg_type == ClientMessageType.INVENTORY:
        outbound.append(await _inventory_msg(character_id))
        return character_id, user_id, outbound, None

    if msg_type == ClientMessageType.SHOP:
        meta = manager.get_meta(character_id)
        if meta and zone_at(int(meta["x"]), int(meta["y"])) != "town":
            outbound.append(msg(ServerMessageType.ERROR, reason="shop only in town"))
            return character_id, user_id, outbound, None
        outbound.append(msg(ServerMessageType.SHOP_LIST, items=shop_catalog()))
        return character_id, user_id, outbound, None

    if msg_type == ClientMessageType.EQUIP:
        if combat_engine.is_in_combat(character_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="in combat"))
            return character_id, user_id, outbound, None
        slot = data.get("slot")
        item_id = data.get("item") or data.get("item_id")
        char = await get_character(character_id)
        if not char:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            return character_id, user_id, outbound, None
        async with db_write() as db:
            ok, reason = await equip_item(db, char, str(slot or ""), str(item_id or ""))
        if not ok:
            outbound.append(msg(ServerMessageType.ERROR, reason=reason))
        outbound.append(await _inventory_msg(character_id))
        return character_id, user_id, outbound, None

    if msg_type == ClientMessageType.UNEQUIP:
        if combat_engine.is_in_combat(character_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="in combat"))
            return character_id, user_id, outbound, None
        slot = data.get("slot")
        char = await get_character(character_id)
        if not char:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            return character_id, user_id, outbound, None
        async with db_write() as db:
            ok, reason = await unequip_item(db, char, str(slot or ""))
        if not ok:
            outbound.append(msg(ServerMessageType.ERROR, reason=reason))
        outbound.append(await _inventory_msg(character_id))
        return character_id, user_id, outbound, None

    if msg_type == ClientMessageType.BUY:
        if combat_engine.is_in_combat(character_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="in combat"))
            return character_id, user_id, outbound, None
        meta = manager.get_meta(character_id)
        if not meta or zone_at(int(meta["x"]), int(meta["y"])) != "town":
            outbound.append(msg(ServerMessageType.ERROR, reason="shop only in town"))
            return character_id, user_id, outbound, None
        item_id = data.get("item") or data.get("item_id")
        char = await get_character(character_id)
        if not char:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            return character_id, user_id, outbound, None
        async with db_write() as db:
            ok, reason = await buy_item(db, char, str(item_id or ""))
        if not ok:
            outbound.append(msg(ServerMessageType.ERROR, reason=reason))
        outbound.append(await _inventory_msg(character_id))
        return character_id, user_id, outbound, None

    if msg_type == ClientMessageType.SELL:
        if combat_engine.is_in_combat(character_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="in combat"))
            return character_id, user_id, outbound, None
        meta = manager.get_meta(character_id)
        if not meta or zone_at(int(meta["x"]), int(meta["y"])) != "town":
            outbound.append(msg(ServerMessageType.ERROR, reason="shop only in town"))
            return character_id, user_id, outbound, None
        item_id = data.get("item") or data.get("item_id")
        char = await get_character(character_id)
        if not char:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            return character_id, user_id, outbound, None
        async with db_write() as db:
            ok, reason = await sell_item(db, char, str(item_id or ""))
        if not ok:
            outbound.append(msg(ServerMessageType.ERROR, reason=reason))
        outbound.append(await _inventory_msg(character_id))
        return character_id, user_id, outbound, None

    # Debug/test: force encounter (ALLOW_DEBUG=1)
    if msg_type == "debug_encounter":
        if not ALLOW_DEBUG:
            outbound.append(msg(ServerMessageType.ERROR, reason="debug disabled"))
            return character_id, user_id, outbound, None
        if combat_engine.is_in_combat(character_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="already in combat"))
            return character_id, user_id, outbound, None
        enemy_id = data.get("enemy") or "slime"
        if get_enemy(str(enemy_id)) is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="unknown enemy"))
            return character_id, user_id, outbound, None
        char = await get_character(character_id)
        if not char:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            return character_id, user_id, outbound, None
        char["known_spells"] = battle_spells_at(int(char["level"]))
        seed = data.get("seed")
        if seed is not None and not isinstance(seed, int):
            seed = None
        battle = combat_engine.start(character_id, char, str(enemy_id), seed=seed)
        start_events = battle._take_batch()
        outbound.append(
            msg(
                ServerMessageType.COMBAT_START,
                enemy=battle.enemy_public(),
                hero=battle.hero_public(),
                legal_actions=battle.legal_actions(),
                events=start_events,
            )
        )
        outbound.append(_combat_update(battle, start_events))
        return character_id, user_id, outbound, None

    outbound.append(msg(ServerMessageType.ERROR, reason=f"unknown or unsupported type: {msg_type}"))
    return character_id, user_id, outbound, None
