import re
import math
from typing import Any

from auth.jwt_handler import decode_access_token
from config import ALLOW_DEBUG, COMBAT_GRACE_SECONDS
from database.db import db_write, get_db
from game.combat_engine import combat_engine
from game.data_loader import battle_spells_at, field_spells_at, get_enemy, get_spell
from game.enemy_spawner import roll_encounter
from game import formulas as F
from game.item_manager import (
    REPEL_STEPS,
    buy_item,
    character_public,
    equip_item,
    equipment_bonuses,
    list_items,
    sell_item,
    shop_catalog,
    unequip_item,
    use_consumable,
)
from game.player_manager import apply_character_patch, get_character, inn_cost, rest_at_inn
from game.rng import Rng
from game.serialize import character_dict
from game.world_manager import (
    DUNGEON_ENTRANCE,
    SPAWN_X,
    SPAWN_Y,
    is_adjacent_step,
    is_walkable,
    map_payload,
    zone_at,
)
from network.protocol import ClientMessageType, ServerMessageType, msg
from network.websocket_manager import CHAT_MAX_LEN, manager

# Strip control chars except space/tab; collapse whitespace for storage display
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


async def _inventory_msg(character_id: int) -> dict:
    db = await get_db()
    char = await get_character(character_id)
    items = await list_items(db, character_id)
    if char:
        char["known_spells"] = battle_spells_at(int(char["level"]))
        char["field_spells"] = field_spells_at(int(char["level"]))
        char = character_public(char, items)
    return msg(ServerMessageType.INVENTORY_UPDATE, items=items, character=char)


async def handle_disconnect(character_id: int) -> None:
    """Persist position; keep combat alive for a grace period so reconnect can resume."""
    meta = manager.get_meta(character_id)
    patch: dict = {}
    if meta is not None:
        patch["world_x"] = meta["x"]
        patch["world_y"] = meta["y"]
        manager.mark_clean(character_id)

    battle = combat_engine.get(character_id)
    if battle is not None and battle.outcome == "ongoing":
        # Soft-save HP/MP but do not end the fight yet
        patch["current_hp"] = max(1, int(battle.hero["hp"]))
        patch["current_mp"] = max(0, int(battle.hero["mp"]))
        combat_engine.mark_disconnected(character_id, COMBAT_GRACE_SECONDS)
    elif battle is not None:
        combat_engine.end(character_id)

    if patch:
        await apply_character_patch(character_id, patch)


async def expire_combat_grace(character_id: int) -> None:
    """Called when reconnect grace expires — end battle without rewards."""
    battle = combat_engine.get(character_id)
    if battle is None:
        combat_engine.clear_disconnect(character_id)
        return
    patch = {
        "current_hp": max(1, int(battle.hero["hp"])),
        "current_mp": max(0, int(battle.hero["mp"])),
    }
    await apply_character_patch(character_id, patch)
    combat_engine.end(character_id)
    manager.set_in_combat(character_id, False)
    await manager.publish_status(character_id, pulse_online=True)


def sanitize_chat(raw: Any) -> str | None:
    """Validate and clean chat text. Returns None if empty/invalid after sanitize."""
    if not isinstance(raw, str):
        return None
    text = _CTRL_RE.sub("", raw)
    text = " ".join(text.split())
    text = text.strip()
    if not text:
        return None
    if len(text) > CHAT_MAX_LEN:
        text = text[:CHAT_MAX_LEN]
    return text


def _combat_update(battle, events: list | None = None) -> dict:
    snap = battle.snapshot()
    return msg(
        ServerMessageType.COMBAT_UPDATE,
        player_hp=snap["hero"]["hp"],
        player_mp=snap["hero"]["mp"],
        player_max_hp=snap["hero"]["max_hp"],
        player_max_mp=snap["hero"]["max_mp"],
        hero=snap["hero"],  # includes status (sleep / stopspell)
        enemy=snap["enemy"],
        events=events or [],
        legal_actions=snap["legal_actions"],
        turn=snap["turn"],
        phase=snap["phase"],
        outcome=snap["outcome"],
    )


async def _persist_battle_end(character_id: int, battle) -> dict:
    patch = battle.character_patch()
    gold_lost = 0
    if battle.outcome == "defeat":
        # DQ1-ish: wake at town, keep XP, lose half gold
        gold = int(str(patch.get("gold", "0")))
        gold_lost = gold - (gold // 2)
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
    if gold_lost:
        char["gold_lost"] = gold_lost
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
        # Echo client timestamp for RTT; include server monotonic for diagnostics
        import time as _time

        client_t = data.get("t")
        pong_body: dict[str, Any] = {
            "t": client_t,
            "server_t": _time.time(),
            "online": len(manager.online_ids()),
            "zones": manager.zone_counts(),
        }
        if character_id is not None:
            pong_body["nearby_count"] = len(manager.ids_nearby(character_id))
            pong_body["session_id"] = manager.session_id(character_id)
        outbound.append(msg(ServerMessageType.PONG, **pong_body))
        if data.get("sync") or data.get("presence"):
            if character_id is not None:
                nearby = manager.nearby_players(character_id)
                outbound.append(
                    msg(
                        ServerMessageType.WORLD_STATE,
                        players=nearby,
                        enemies=[],
                        map=map_payload(),
                        online=len(manager.online_ids()),
                    )
                )
        return character_id, user_id, outbound, None

    if msg_type == ClientMessageType.SYNC or msg_type == "sync":
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        # Repair AOI drift so peers re-appear after desync / reconnect storms
        aoi_msgs = await manager.rebuild_aoi(character_id)
        outbound.extend(aoi_msgs)
        meta = manager.get_meta(character_id)
        nearby = manager.nearby_players(character_id)
        sync_zone = None
        if meta is not None:
            try:
                sync_zone = zone_at(int(meta["x"]), int(meta["y"]))
            except Exception:
                sync_zone = None
        outbound.append(
            msg(
                ServerMessageType.WORLD_STATE,
                players=nearby,
                enemies=[],
                map=map_payload(),
                online=len(manager.online_ids()),
                you=(
                    {
                        "x": meta["x"],
                        "y": meta["y"],
                        "zone": sync_zone,
                    }
                    if meta
                    else None
                ),
                repel=manager.repel_remaining(character_id),
                radiant=manager.radiant_remaining(character_id),
                zone=sync_zone,
            )
        )
        return character_id, user_id, outbound, None

    if msg_type in (ClientMessageType.WHO, "who", "players", "online_list"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        meta = manager.get_meta(character_id)
        nearby = manager.nearby_players(character_id)
        you_zone = None
        if meta is not None:
            try:
                you_zone = zone_at(int(meta["x"]), int(meta["y"]))
            except Exception:
                you_zone = None
        from network.websocket_manager import _is_idle

        outbound.append(
            msg(
                ServerMessageType.WHO,
                players=nearby,
                nearby_count=len(nearby),
                online=len(manager.online_ids()),
                online_ids=manager.online_ids(),
                roster=manager.online_roster(),
                zones=manager.zone_counts(),
                you={
                    "id": character_id,
                    "name": (meta or {}).get("name"),
                    "level": (meta or {}).get("level"),
                    "x": meta["x"] if meta else None,
                    "y": meta["y"] if meta else None,
                    "in_combat": bool(meta.get("in_combat")) if meta else False,
                    "idle": _is_idle(meta) if meta else False,
                    "repel": manager.repel_remaining(character_id),
                    "radiant": manager.radiant_remaining(character_id),
                    "zone": you_zone,
                },
            )
        )
        return character_id, user_id, outbound, None

    # --- Nearby-only roster (lighter than full /who) ---
    if msg_type in ("near", "nearby_list", "here"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        nearby = manager.nearby_players(character_id)
        meta = manager.get_meta(character_id)
        you_zone = None
        if meta is not None:
            try:
                you_zone = zone_at(int(meta["x"]), int(meta["y"]))
            except Exception:
                you_zone = None
        outbound.append(
            msg(
                "near",
                players=nearby,
                nearby_count=len(nearby),
                online=len(manager.online_ids()),
                zone=you_zone,
            )
        )
        return character_id, user_id, outbound, None

    # --- Where am I / zone population (multiplayer social) ---
    if msg_type in ("zone", "where", "area"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        meta = manager.get_meta(character_id)
        you_zone = None
        x = y = None
        if meta is not None:
            try:
                x, y = int(meta["x"]), int(meta["y"])
                you_zone = zone_at(x, y)
            except Exception:
                you_zone = None
        zones = manager.zone_counts()
        # Same-zone roster (public cards, no x/y) for multiplayer social overview
        mates = manager.zone_roster(character_id, include_self=True)
        zone_pop = int(zones.get(you_zone, 0)) if you_zone else len(mates)
        outbound.append(
            msg(
                "zone",
                zone=you_zone,
                x=x,
                y=y,
                zones=zones,
                players=mates,
                zone_count=len(mates),
                population=zone_pop,
                online=len(manager.online_ids()),
                message=(
                    f"You are in the {you_zone} ({len(mates)} here)."
                    if you_zone in ("town", "field", "dungeon")
                    else "You are somewhere on the map."
                ),
            )
        )
        return character_id, user_id, outbound, None

    # --- Look / examine (public card; full coords only if nearby) ---
    if msg_type in (ClientMessageType.LOOK, ClientMessageType.EXAMINE, "look", "examine"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        target_name = data.get("name") or data.get("to") or data.get("target") or data.get("player")
        target_id = data.get("player_id") or data.get("id")
        tid: int | None = None
        if target_id is not None:
            try:
                tid = int(target_id)
            except (TypeError, ValueError):
                tid = None
        if tid is None and isinstance(target_name, str):
            tid = manager.find_id_by_name(target_name)
        if tid is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="player not found"))
            return character_id, user_id, outbound, None
        tmeta = manager.get_meta(tid)
        if tmeta is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        nearby_ids = set(manager.ids_nearby(character_id))
        is_near = tid == character_id or tid in nearby_ids
        card = {
            "id": tid,
            "name": tmeta.get("name"),
            "level": tmeta.get("level"),
            "in_combat": bool(tmeta.get("in_combat")),
            "nearby": is_near,
        }
        if is_near:
            card["x"] = tmeta.get("x")
            card["y"] = tmeta.get("y")
            card["map_id"] = tmeta.get("map_id")
        # Soft AFK flag (no coords when far)
        try:
            from network.websocket_manager import _is_idle

            card["idle"] = _is_idle(tmeta)
        except Exception:
            card["idle"] = False
        outbound.append(msg(ServerMessageType.LOOK, player=card))
        return character_id, user_id, outbound, None

    # --- Self status (lightweight sheet; no inventory dump) ---
    if msg_type in (ClientMessageType.STATUS, ClientMessageType.ME, "status", "me"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        char = await get_character(character_id)
        meta = manager.get_meta(character_id)
        if not char:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            return character_id, user_id, outbound, None
        x = int(meta["x"]) if meta else int(char.get("world_x") or SPAWN_X)
        y = int(meta["y"]) if meta else int(char.get("world_y") or SPAWN_Y)
        try:
            z = zone_at(x, y)
        except Exception:
            z = None
        from game.progression import xp_to_next_level

        xp_prog = xp_to_next_level(
            int(char.get("experience") or 0),
            int(char.get("level") or 1),
        )
        bonuses = equipment_bonuses(char)
        outbound.append(
            msg(
                ServerMessageType.STATUS,
                character={
                    "id": character_id,
                    "name": char.get("name"),
                    "level": char.get("level"),
                    "current_hp": char.get("current_hp"),
                    "max_hp": char.get("max_hp"),
                    "current_mp": char.get("current_mp"),
                    "max_mp": char.get("max_mp"),
                    "gold": char.get("gold"),
                    "strength": char.get("strength"),
                    "agility": char.get("agility"),
                    "experience": char.get("experience"),
                    "xp_progress": xp_prog,
                    "equipment_weapon": char.get("equipment_weapon"),
                    "equipment_armor": char.get("equipment_armor"),
                    "equipment_shield": char.get("equipment_shield"),
                    "equipment_helmet": char.get("equipment_helmet"),
                    "bonuses": bonuses,
                    "known_spells": battle_spells_at(int(char.get("level") or 1)),
                    "field_spells": field_spells_at(int(char.get("level") or 1)),
                },
                you={
                    "x": x,
                    "y": y,
                    "zone": z,
                    "in_combat": combat_engine.is_in_combat(character_id),
                    "repel": manager.repel_remaining(character_id),
                    "radiant": manager.radiant_remaining(character_id),
                    "session_id": manager.session_id(character_id),
                },
                online=len(manager.online_ids()),
            )
        )
        return character_id, user_id, outbound, None

    # --- Help (slash/key command list for clients) ---
    if msg_type in (ClientMessageType.HELP, "help", "commands"):
        if character_id is not None:
            manager.touch(character_id)
        outbound.append(
            msg(
                ServerMessageType.HELP,
                commands=[
                    {"cmd": "move", "hint": "WASD / arrow keys"},
                    {"cmd": "chat", "hint": "T global · Y nearby · /z zone"},
                    {"cmd": "whisper", "hint": "/w Name message"},
                    {"cmd": "say", "hint": "/say · /s message — nearby chat"},
                    {"cmd": "find", "hint": "/find Name · /find zone:town · zone:field"},
                    {"cmd": "status", "hint": "F or /status — self sheet"},
                    {"cmd": "look", "hint": "L — examine a player"},
                    {"cmd": "who", "hint": "O · /who · /players — online + zone counts"},
                    {"cmd": "near", "hint": "/near · /here — nearby heroes only"},
                    {"cmd": "zone", "hint": "/zone · /where — area + who is here"},
                    {"cmd": "emote", "hint": "E · /emote wave — nearby emotes"},
                    {"cmd": "rest", "hint": "R — inn (town only)"},
                    {"cmd": "inventory", "hint": "I — bag (12 stacks · max 8) / shop"},
                    {"cmd": "use_spell", "hint": "H heal · M cycle field magic"},
                    {"cmd": "combat", "hint": "1–9 menu · A attack · F flee · H herb"},
                    {"cmd": "ignore", "hint": "/ignore · /unignore · /ignores"},
                    {"cmd": "reply", "hint": "/r message — reply last whisper (server-tracked)"},
                ],
                channels=["global", "nearby", "zone", "whisper"],
                version=__import__("config", fromlist=["VERSION"]).VERSION,
                online=len(manager.online_ids()),
            )
        )
        return character_id, user_id, outbound, None

    # --- Ignore / mute list (session soft-grace) ---
    if msg_type in (ClientMessageType.IGNORE, "ignore", "mute"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        target_name = data.get("name") or data.get("to") or data.get("player")
        target_id = manager.find_id_by_player_id(
            data.get("player_id") or data.get("id") or data.get("to_id")
        )
        if target_id is None and isinstance(target_name, str):
            target_id = manager.find_id_by_name(target_name)
        if target_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        ok, reason = manager.ignore_player(character_id, target_id)
        if not ok:
            outbound.append(msg(ServerMessageType.ERROR, reason=reason))
            return character_id, user_id, outbound, None
        tmeta = manager.get_meta(target_id)
        outbound.append(
            msg(
                ServerMessageType.IGNORE,
                action="ignore",
                ok=True,
                reason=reason,
                player={
                    "id": target_id,
                    "name": (tmeta or {}).get("name"),
                },
                ignores=manager.ignore_list(character_id),
            )
        )
        return character_id, user_id, outbound, None

    if msg_type in (ClientMessageType.UNIGNORE, "unignore", "unmute"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        target_name = data.get("name") or data.get("to") or data.get("player")
        target_id = manager.find_id_by_player_id(
            data.get("player_id") or data.get("id") or data.get("to_id")
        )
        if target_id is None and isinstance(target_name, str):
            target_id = manager.find_id_by_name(target_name)
        if target_id is None:
            # allow unignore by id even if offline
            try:
                target_id = int(data.get("player_id") or data.get("id") or 0) or None
            except (TypeError, ValueError):
                target_id = None
        if target_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="player not found"))
            return character_id, user_id, outbound, None
        ok, reason = manager.unignore_player(character_id, target_id)
        if not ok:
            outbound.append(msg(ServerMessageType.ERROR, reason=reason))
            return character_id, user_id, outbound, None
        outbound.append(
            msg(
                ServerMessageType.IGNORE,
                action="unignore",
                ok=True,
                reason=reason,
                player_id=target_id,
                ignores=manager.ignore_list(character_id),
            )
        )
        return character_id, user_id, outbound, None

    if msg_type in (ClientMessageType.IGNORES, "ignores", "ignore_list"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        outbound.append(
            msg(
                ServerMessageType.IGNORE,
                action="list",
                ignores=manager.ignore_list(character_id),
            )
        )
        return character_id, user_id, outbound, None

    # --- Find online players by name prefix (no coordinates) ---
    if msg_type in (ClientMessageType.FIND, "find", "search"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        q = data.get("q") or data.get("query") or data.get("name") or data.get("prefix") or ""
        zone_f = data.get("zone") or data.get("area")
        q_clean = q.strip() if isinstance(q, str) else ""
        # "/find bob zone:field" or "/find zone:town" (zone-only list)
        if isinstance(q_clean, str) and q_clean:
            m = re.search(
                r"^(?:(.+?)\s+)?(?:zone|in):(\w+)\s*$",
                q_clean,
                flags=re.I,
            )
            if m:
                name_part = (m.group(1) or "").strip()
                zone_f = m.group(2)
                q_clean = name_part
        # Validate zone first so "zone:moon" → invalid zone (not "find query required")
        if isinstance(zone_f, str) and zone_f.strip():
            znorm = zone_f.strip().lower()
            if znorm not in ("town", "field", "dungeon"):
                outbound.append(msg(ServerMessageType.ERROR, reason="invalid zone"))
                return character_id, user_id, outbound, None
            zone_f = znorm
        else:
            zone_f = None
        # Bare zone field with empty name is OK (list everyone in zone)
        if not q_clean and zone_f is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="find query required"))
            return character_id, user_id, outbound, None
        limit = data.get("limit") or 20
        try:
            limit_i = int(limit)
        except (TypeError, ValueError):
            limit_i = 20
        hits = manager.find_by_prefix(q_clean, limit=limit_i, zone=zone_f)
        outbound.append(
            msg(
                ServerMessageType.FIND,
                query=q_clean[:24] if q_clean else (f"zone:{zone_f}" if zone_f else ""),
                zone=zone_f,
                players=hits,
                online=len(manager.online_ids()),
                count=len(hits),
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

        character["known_spells"] = battle_spells_at(int(character["level"]))
        character["field_spells"] = field_spells_at(int(character["level"]))
        character["bonuses"] = equipment_bonuses(character)
        from game.progression import xp_to_next_level

        character["xp_progress"] = xp_to_next_level(
            int(character.get("experience") or 0),
            int(character.get("level") or 1),
        )

        resume_battle = combat_engine.get(character["id"])
        if resume_battle is not None and resume_battle.outcome == "ongoing":
            combat_engine.clear_disconnect(character["id"])
            character["current_hp"] = resume_battle.hero["hp"]
            character["current_mp"] = resume_battle.hero["mp"]
            character["in_combat"] = True
        else:
            character["in_combat"] = False
            if resume_battle is not None:
                combat_engine.end(character["id"])

        connect_meta = {
            "character_id": character["id"],
            "name": character["name"],
            "x": character["world_x"],
            "y": character["world_y"],
            "map_id": character["map_id"],
            "level": character["level"],
            "in_combat": bool(character.get("in_combat")),
        }

        outbound.append(
            msg(
                ServerMessageType.AUTH_OK,
                player_id=character["id"],
                character=character,
                map=map_payload(),
                in_combat=bool(character.get("in_combat")),
            )
        )
        outbound.append(msg(ServerMessageType.WORLD_STATE, players=[], enemies=[], map=map_payload()))

        if resume_battle is not None and resume_battle.outcome == "ongoing":
            snap = resume_battle.snapshot()
            outbound.append(
                msg(
                    ServerMessageType.COMBAT_RESUME,
                    enemy=snap["enemy"],
                    hero=snap["hero"],
                    legal_actions=snap["legal_actions"],
                    turn=snap["turn"],
                    phase=snap["phase"],
                    events=[{"kind": "message", "message": "Battle resumed!"}],
                )
            )
            outbound.append(_combat_update(resume_battle, []))

        return character["id"], payload["user_id"], outbound, connect_meta

    if character_id is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
        return character_id, user_id, outbound, None

    # Drop ghost sessions if the hero row was deleted while still connected
    _needs_char = msg_type in (
        ClientMessageType.MOVE,
        ClientMessageType.ATTACK,
        ClientMessageType.FLEE,
        ClientMessageType.USE_SPELL,
        ClientMessageType.USE_ITEM,
        ClientMessageType.EQUIP,
        ClientMessageType.UNEQUIP,
        ClientMessageType.BUY,
        ClientMessageType.SELL,
        ClientMessageType.REST,
        ClientMessageType.SHOP,
        ClientMessageType.INVENTORY,
        "use_spell",
        "use_item",
        "rest",
        "inn",
        "debug_encounter",
        "combat_action",
    )
    if _needs_char:
        _alive = await get_character(character_id)
        if _alive is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            try:
                await manager.disconnect(character_id)
            except Exception:
                pass
            return character_id, user_id, outbound, None

    # --- Field magic (overworld) ---
    if msg_type in (ClientMessageType.USE_SPELL, "use_spell") and not combat_engine.is_in_combat(
        character_id
    ):
        spell_id = str(data.get("spell") or data.get("id") or "")
        char = await get_character(character_id)
        if not char:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            return character_id, user_id, outbound, None
        known = field_spells_at(int(char["level"]))
        # also allow known_spells from battle list if field flag set
        if spell_id not in known:
            outbound.append(msg(ServerMessageType.ERROR, reason="unknown or unlearned spell"))
            return character_id, user_id, outbound, None
        sp = get_spell(spell_id)
        if not sp or not sp.get("field"):
            outbound.append(msg(ServerMessageType.ERROR, reason="cannot cast on field"))
            return character_id, user_id, outbound, None
        cost = int(sp.get("mp_cost") or 0)
        mp = int(char.get("current_mp") or 0)
        if mp < cost:
            outbound.append(msg(ServerMessageType.ERROR, reason="not enough MP"))
            return character_id, user_id, outbound, None

        rng = Rng()
        meta = manager.get_meta(character_id)
        patch: dict = {"current_mp": mp - cost}
        info: dict = {
            "spell": spell_id,
            "name": sp.get("name") or spell_id,
            "mp_cost": cost,
            "current_mp": mp - cost,
        }
        formula = sp.get("formula") or spell_id

        if formula in ("heal", "healmore"):
            max_hp = int(char.get("max_hp") or 1)
            cur_hp = int(char.get("current_hp") or 0)
            if cur_hp >= max_hp:
                outbound.append(msg(ServerMessageType.ERROR, reason="already at full HP"))
                return character_id, user_id, outbound, None
            amt = F.heal_amount(rng) if formula == "heal" else F.healmore_amount(rng)
            new_hp, actual = F.apply_heal(cur_hp, max_hp, amt)
            patch["current_hp"] = new_hp
            info.update(
                {
                    "healed": actual,
                    "current_hp": new_hp,
                    "max_hp": max_hp,
                    "message": f"You cast {sp.get('name')}! Recovered {actual} HP.",
                }
            )
        elif formula == "return" or spell_id == "return":
            patch["world_x"] = SPAWN_X
            patch["world_y"] = SPAWN_Y
            info.update(
                {
                    "teleported": True,
                    "x": SPAWN_X,
                    "y": SPAWN_Y,
                    "message": f"You cast {sp.get('name')}! Returned to town.",
                }
            )
        elif formula == "repel" or spell_id == "repel":
            manager.set_repel(character_id, REPEL_STEPS)
            info.update(
                {
                    "repel_steps": REPEL_STEPS,
                    "message": f"You cast {sp.get('name')}! Foes keep away for a while.",
                }
            )
        elif spell_id == "outside":
            zone = zone_at(int(meta["x"]), int(meta["y"])) if meta else "blocked"
            if zone != "dungeon":
                outbound.append(msg(ServerMessageType.ERROR, reason="only works in dungeon"))
                return character_id, user_id, outbound, None
            # Exit to field just west of dungeon mouth
            ox, oy = 14, 3
            if not is_walkable(ox, oy):
                ox, oy = DUNGEON_ENTRANCE[0] - 1, DUNGEON_ENTRANCE[1]
            patch["world_x"] = ox
            patch["world_y"] = oy
            info.update(
                {
                    "teleported": True,
                    "x": ox,
                    "y": oy,
                    "message": f"You cast {sp.get('name')}! You exit the dungeon.",
                }
            )
        elif spell_id == "radiant":
            steps = int(getattr(manager, "RADIANT_STEPS", 64) or 64)
            manager.set_radiant(character_id, steps)
            info.update(
                {
                    "radiant_steps": steps,
                    "message": (
                        f"You cast {sp.get('name')}! A soft light surrounds you "
                        f"({steps} steps — safer in dungeons)."
                    ),
                }
            )
        else:
            outbound.append(msg(ServerMessageType.ERROR, reason="cannot cast on field"))
            return character_id, user_id, outbound, None

        char = await apply_character_patch(character_id, patch) or char
        if info.get("teleported"):
            aoi = await manager.publish_move(character_id, int(info["x"]), int(info["y"]), seq=None)
            outbound.extend(aoi)
            outbound.append(
                msg(
                    ServerMessageType.MOVE_OK,
                    ok=True,
                    x=int(info["x"]),
                    y=int(info["y"]),
                    seq=None,
                    reason="spell",
                )
            )
        char["known_spells"] = battle_spells_at(int(char["level"]))
        char["field_spells"] = field_spells_at(int(char["level"]))
        char["bonuses"] = equipment_bonuses(char)
        outbound.append(
            msg(ServerMessageType.SPELL_CAST, character=char, **info)
        )
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

        # Field-only spells must not be mis-routed as battle actions mid-fight
        if msg_type in (ClientMessageType.USE_SPELL, "use_spell"):
            sid = str(data.get("spell") or data.get("id") or "")
            sp = get_spell(sid) if sid else None
            if sp and sp.get("field") and not sp.get("battle"):
                outbound.append(
                    msg(ServerMessageType.ERROR, reason="in combat")
                )
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
                if e.get("level") is not None:
                    await manager.publish_level(character_id, int(e["level"]))

        if battle.outcome != "ongoing":
            char = await _persist_battle_end(character_id, battle)
            combat_engine.end(character_id)
            manager.set_in_combat(character_id, False)
            if char.get("level"):
                manager.set_level(character_id, int(char["level"]))
            await manager.publish_status(character_id, pulse_online=True)
            end_payload = {
                "result": battle.outcome,
                "xp": (battle.rewards or {}).get("xp", 0),
                "gold": (battle.rewards or {}).get("gold", 0),
                "character": char,
                "events": events,
            }
            if battle.outcome == "defeat":
                end_payload["gold_lost"] = int(char.pop("gold_lost", 0) or 0)
                end_payload["respawn"] = {"x": SPAWN_X, "y": SPAWN_Y}
            outbound.append(msg(ServerMessageType.COMBAT_END, **end_payload))
            if battle.outcome == "defeat":
                # Multiplayer: nearby system note that the hero fell
                hero = (manager.get_meta(character_id) or {}).get("name") or "Hero"
                await manager.broadcast_nearby(
                    character_id,
                    msg(
                        ServerMessageType.CHAT,
                        player_id=character_id,
                        name="System",
                        text=f"{hero} was defeated!",
                        channel="system",
                        system=True,
                    ),
                    include_self=True,
                    respect_ignore=False,
                )
                # Respawn in town with AOI refresh
                aoi_msgs = await manager.publish_move(
                    character_id, SPAWN_X, SPAWN_Y, seq=None
                )
                outbound.extend(aoi_msgs)
                try:
                    rzone = zone_at(SPAWN_X, SPAWN_Y)
                except Exception:
                    rzone = "town"
                rmsg = msg(
                    ServerMessageType.MOVE_OK,
                    ok=True,
                    x=SPAWN_X,
                    y=SPAWN_Y,
                    seq=None,
                    reason="respawn",
                    zone=rzone,
                )
                outbound.append(rmsg)
        return character_id, user_id, outbound, None

    # --- Movement (server-authoritative, ack'd, rate-limited, DB-deferred) ---
    if msg_type == ClientMessageType.MOVE:
        raw_seq = data.get("seq")
        seq: int | None
        # bool is a subclass of int — reject before numeric coercion
        if isinstance(raw_seq, bool):
            seq = None
            _bad_seq = True
        elif isinstance(raw_seq, int):
            seq = raw_seq
            _bad_seq = False
        elif isinstance(raw_seq, float):
            seq = int(raw_seq)
            _bad_seq = False
        elif isinstance(raw_seq, str) and raw_seq.strip().lstrip("-").isdigit():
            # Loose clients may send "2" — coerce digit strings
            seq = int(raw_seq.strip())
            _bad_seq = False
        elif raw_seq is None:
            seq = None
            _bad_seq = False  # seq optional
        else:
            seq = None
            _bad_seq = True
        # Reject non-positive seq (client always starts at 1; negatives used to
        # trip the duplicate path because last_move_seq defaults to 0).
        if _bad_seq or (seq is not None and seq < 1):
            meta = manager.get_meta(character_id)
            mx = int(meta["x"]) if meta else 0
            my = int(meta["y"]) if meta else 0
            outbound.append(
                msg(
                    ServerMessageType.MOVE_OK,
                    ok=False,
                    x=mx,
                    y=my,
                    seq=seq if isinstance(seq, int) and not isinstance(raw_seq, bool) else None,
                    reason="invalid seq",
                )
            )
            return character_id, user_id, outbound, None

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

        def _finite_num(v: Any) -> bool:
            return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))

        if not _finite_num(x) or not _finite_num(y):
            meta = manager.get_meta(character_id)
            try:
                mx = int(meta["x"]) if meta and math.isfinite(float(meta["x"])) else 0
                my = int(meta["y"]) if meta and math.isfinite(float(meta["y"])) else 0
            except (TypeError, ValueError, OverflowError):
                mx, my = 0, 0
            _reject("invalid move", mx, my)
            return character_id, user_id, outbound, None

        # Reject non-integer coords (3.7 must not silently become 3 — desyncs clients)
        try:
            fx_n, fy_n = float(x), float(y)
            if not fx_n.is_integer() or not fy_n.is_integer():
                meta = manager.get_meta(character_id)
                mx = int(meta["x"]) if meta else 0
                my = int(meta["y"]) if meta else 0
                _reject("invalid move", mx, my)
                return character_id, user_id, outbound, None
            tx, ty = int(fx_n), int(fy_n)
        except (TypeError, ValueError, OverflowError):
            meta = manager.get_meta(character_id)
            mx = int(meta["x"]) if meta else 0
            my = int(meta["y"]) if meta else 0
            _reject("invalid move", mx, my)
            return character_id, user_id, outbound, None
        meta = manager.get_meta(character_id)
        if meta is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="not connected"))
            return character_id, user_id, outbound, None

        # Defend against corrupted meta (e.g. prior non-finite inject)
        try:
            fx, fy = int(meta["x"]), int(meta["y"])
            if not math.isfinite(float(meta["x"])) or not math.isfinite(float(meta["y"])):
                raise ValueError("non-finite meta pos")
        except (TypeError, ValueError, OverflowError):
            fx, fy = SPAWN_X, SPAWN_Y
            meta["x"], meta["y"] = float(fx), float(fy)

        # Duplicate / old seq: ignore but confirm current pos (idempotent)
        last_seq = int(meta.get("last_move_seq") or 0)
        if seq is not None and seq <= last_seq:
            outbound.append(
                msg(ServerMessageType.MOVE_OK, ok=True, x=fx, y=fy, seq=seq, duplicate=True)
            )
            return character_id, user_id, outbound, None

        # Validate geometry before burning the move rate budget — rejected
        # wall/non-adjacent steps must not lock the player out of the next step.
        if not is_adjacent_step(fx, fy, tx, ty):
            _reject("invalid step", fx, fy)
            return character_id, user_id, outbound, None

        if not is_walkable(tx, ty):
            _reject("blocked", fx, fy)
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

        # Apply position + AOI (enter/leave range notifications)
        aoi_msgs = await manager.publish_move(character_id, tx, ty, seq=seq)
        new_zone = zone_at(tx, ty)
        old_zone = zone_at(fx, fy)
        outbound.append(
            msg(
                ServerMessageType.MOVE_OK,
                ok=True,
                x=tx,
                y=ty,
                seq=seq,
                zone=new_zone,
            )
        )
        outbound.extend(aoi_msgs)

        # Multiplayer: soft nearby system note when crossing zone types
        # (town ↔ field ↔ dungeon). Quiet for same-zone steps.
        if (
            old_zone != new_zone
            and old_zone in ("town", "field", "dungeon")
            and new_zone in ("town", "field", "dungeon")
        ):
            meta_now = manager.get_meta(character_id)
            hero = (meta_now or {}).get("name") or "Hero"
            await manager.broadcast_nearby(
                character_id,
                msg(
                    ServerMessageType.CHAT,
                    player_id=character_id,
                    name="System",
                    text=f"{hero} entered the {new_zone}.",
                    channel="system",
                    system=True,
                    zone=new_zone,
                ),
                include_self=True,
                respect_ignore=False,
            )

        # Fairy Water / REPEL: consume a step; while active, skip random fights
        if manager.consume_repel_step(character_id):
            return character_id, user_id, outbound, None

        # RADIANT: soft light in dungeons (lower encounter rate); tick each step
        lit = manager.radiant_remaining(character_id) > 0
        if lit:
            # Only consume steps while light is "used" (any zone) so duration is finite
            manager.consume_radiant_step(character_id)

        # Random encounter (radiant reduces dungeon rate)
        enemy_id = roll_encounter(tx, ty, Rng(), radiant=lit)
        if enemy_id:
            async with db_write() as db:
                await db.execute(
                    "UPDATE characters SET world_x = ?, world_y = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (tx, ty, character_id),
                )
                await db.commit()
            manager.mark_clean(character_id)

            char = await get_character(character_id)
            if char and not combat_engine.is_in_combat(character_id):
                char["known_spells"] = battle_spells_at(int(char["level"]))
                try:
                    battle = combat_engine.start(character_id, char, enemy_id)
                except RuntimeError:
                    # Concurrent start race — leave player out of a forced fight
                    return character_id, user_id, outbound, None
                manager.set_in_combat(character_id, True)
                await manager.publish_status(character_id, pulse_online=True)
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

    # --- Whisper / tell / reply (private, by name or player_id or last peer) ---
    if msg_type in (
        ClientMessageType.WHISPER,
        ClientMessageType.TELL,
        ClientMessageType.REPLY,
        "whisper",
        "tell",
        "reply",
    ):
        text = sanitize_chat(data.get("text") or data.get("message") or data.get("msg"))
        if text is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="empty chat"))
            return character_id, user_id, outbound, None
        # Server-side reply: use last whisper peer (survives soft reconnect)
        want_reply = (
            msg_type in (ClientMessageType.REPLY, "reply")
            or bool(data.get("reply"))
            or str(data.get("to") or "").strip().lower() in ("@last", "last", "!")
        )
        target_name = data.get("to") or data.get("name") or data.get("target") or data.get("player")
        if want_reply and (
            target_name is None
            or str(target_name).strip().lower() in ("@last", "last", "!", "")
        ):
            lid, lname = manager.last_whisper_from(character_id)
            target_id = lid if lid is not None else None
            if target_id is None:
                outbound.append(msg(ServerMessageType.ERROR, reason="no one to reply to"))
                return character_id, user_id, outbound, None
            target_name = lname
        else:
            target_id = manager.find_id_by_player_id(
                data.get("to_id") or data.get("player_id") or data.get("id")
            )
            if target_id is None and isinstance(target_name, str) and target_name.strip():
                target_id = manager.find_id_by_name(target_name)
            if target_id is None and not (
                isinstance(target_name, str) and target_name.strip()
            ) and data.get("to_id") is None and data.get("player_id") is None:
                outbound.append(msg(ServerMessageType.ERROR, reason="whisper target required"))
                return character_id, user_id, outbound, None
        # Validate target BEFORE burning chat rate (self/offline must not rate-limit)
        if target_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        # Reply target may have gone offline — re-check online
        if target_id not in manager.online_ids():
            outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        if target_id == character_id:
            outbound.append(msg(ServerMessageType.ERROR, reason="cannot whisper yourself"))
            return character_id, user_id, outbound, None
        # Target has ignored us — silent-ish failure (privacy)
        if manager.is_ignored_by(target_id, character_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="player unavailable"))
            return character_id, user_id, outbound, None
        # We have ignored them — don't allow whispering ignored players
        if manager.is_ignored_by(character_id, target_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="you ignore that player"))
            return character_id, user_id, outbound, None
        allowed, retry = manager.allow_chat(character_id)
        if not allowed:
            outbound.append(
                msg(
                    ServerMessageType.ERROR,
                    reason="chat_rate_limit",
                    retry_after=round(retry, 3),
                )
            )
            return character_id, user_id, outbound, None
        meta = manager.get_meta(character_id)
        tmeta = manager.get_meta(target_id)
        name = (meta or {}).get("name") or "Hero"
        tname = (tmeta or {}).get("name") or (
            target_name.strip() if isinstance(target_name, str) else "Hero"
        )
        whisper_msg = msg(
            ServerMessageType.CHAT,
            player_id=character_id,
            name=name,
            text=text,
            channel="whisper",
            to=tname,
            to_id=target_id,
        )
        # Deliver to target + echo to self (so UI shows the send)
        await manager.send(target_id, whisper_msg)
        outbound.append(whisper_msg)
        # Target remembers us for their /r; we remember them if they reply later
        manager.note_whisper_from(target_id, character_id, name)
        manager.note_whisper_from(character_id, target_id, tname)
        return character_id, user_id, outbound, None

    # --- Chat: global / nearby AOI / zone (`say` defaults nearby) ---
    if msg_type in (ClientMessageType.CHAT, ClientMessageType.SAY, "chat", "say"):
        text = sanitize_chat(data.get("text") or data.get("message") or data.get("msg"))
        if text is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="empty chat"))
            return character_id, user_id, outbound, None
        meta = manager.get_meta(character_id)
        name = (meta or {}).get("name") or "Hero"
        # Explicit channel wins; `say` defaults nearby, `chat` defaults global
        channel = (data.get("channel") or "").lower().strip()
        # Reserved for server-originated traffic only (level-up fanfare, etc.)
        # Check before rate-limit so clients get a clear reason, not chat_rate_limit.
        if channel in ("system", "admin", "server", "gm"):
            outbound.append(
                msg(ServerMessageType.ERROR, reason="reserved channel")
            )
            return character_id, user_id, outbound, None
        if channel not in ("global", "nearby", "local", "whisper", "zone", "area"):
            if msg_type in (ClientMessageType.SAY, "say"):
                channel = "nearby"
            else:
                channel = "global"
        if channel == "local":
            channel = "nearby"
        if channel == "area":
            channel = "zone"
        # chat with channel=whisper and `to` name/id → private path
        # Validate target BEFORE burning chat rate (same as dedicated whisper handler)
        if channel == "whisper":
            target_name = data.get("to") or data.get("name") or data.get("target")
            target_id = manager.find_id_by_player_id(
                data.get("to_id") or data.get("player_id") or data.get("id")
            )
            if target_id is None and isinstance(target_name, str) and target_name.strip():
                target_id = manager.find_id_by_name(target_name)
            if target_id is None and not (
                isinstance(target_name, str) and target_name.strip()
            ):
                outbound.append(msg(ServerMessageType.ERROR, reason="whisper target required"))
                return character_id, user_id, outbound, None
            if target_id is None:
                outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
                return character_id, user_id, outbound, None
            if target_id not in manager.online_ids():
                outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
                return character_id, user_id, outbound, None
            if target_id == character_id:
                outbound.append(msg(ServerMessageType.ERROR, reason="cannot whisper yourself"))
                return character_id, user_id, outbound, None
            if manager.is_ignored_by(target_id, character_id):
                outbound.append(msg(ServerMessageType.ERROR, reason="player unavailable"))
                return character_id, user_id, outbound, None
            if manager.is_ignored_by(character_id, target_id):
                outbound.append(msg(ServerMessageType.ERROR, reason="you ignore that player"))
                return character_id, user_id, outbound, None
            allowed, retry = manager.allow_chat(character_id)
            if not allowed:
                outbound.append(
                    msg(
                        ServerMessageType.ERROR,
                        reason="chat_rate_limit",
                        retry_after=round(retry, 3),
                    )
                )
                return character_id, user_id, outbound, None
            tmeta = manager.get_meta(target_id)
            tname = (tmeta or {}).get("name") or (
                target_name.strip() if isinstance(target_name, str) else "Hero"
            )
            whisper_msg = msg(
                ServerMessageType.CHAT,
                player_id=character_id,
                name=name,
                text=text,
                channel="whisper",
                to=tname,
                to_id=target_id,
            )
            await manager.send(target_id, whisper_msg)
            outbound.append(whisper_msg)
            manager.note_whisper_from(target_id, character_id, name)
            manager.note_whisper_from(character_id, target_id, tname)
            return character_id, user_id, outbound, None
        allowed, retry = manager.allow_chat(character_id)
        if not allowed:
            outbound.append(
                msg(
                    ServerMessageType.ERROR,
                    reason="chat_rate_limit",
                    retry_after=round(retry, 3),
                )
            )
            return character_id, user_id, outbound, None
        zone_name = None
        if meta is not None:
            try:
                zone_name = zone_at(int(meta["x"]), int(meta["y"]))
            except Exception:
                zone_name = None
        chat_msg = msg(
            ServerMessageType.CHAT,
            player_id=character_id,
            name=name,
            text=text,
            channel=channel,
            zone=zone_name if channel == "zone" else None,
        )
        # Peers via broadcast (exclude self); self always via outbound once
        # so local UI never loses the echo if a peer-send races/fails.
        if channel == "nearby":
            await manager.broadcast_nearby(
                character_id, chat_msg, include_self=False, respect_ignore=True
            )
        elif channel == "zone":
            await manager.broadcast_zone(
                character_id, chat_msg, include_self=False, respect_ignore=True
            )
        else:
            await manager.broadcast(
                chat_msg,
                exclude=character_id,
                from_id=character_id,
                respect_ignore=True,
            )
        outbound.append(chat_msg)
        return character_id, user_id, outbound, None

    # --- Emotes (nearby only) ---
    if msg_type in (ClientMessageType.EMOTE, "emote"):
        raw_emote = data.get("emote")
        if raw_emote is None:
            raw_emote = data.get("id")
        if raw_emote is None:
            raw_emote = data.get("action")
        if raw_emote is None:
            raw_emote = "wave"  # bare {type:emote} defaults to wave
        if not isinstance(raw_emote, str):
            outbound.append(msg(ServerMessageType.ERROR, reason="bad emote"))
            return character_id, user_id, outbound, None
        emote = raw_emote.strip().lower()[:24]
        if not emote:
            outbound.append(msg(ServerMessageType.ERROR, reason="bad emote"))
            return character_id, user_id, outbound, None
        allowed = {
            "wave",
            "bow",
            "cheer",
            "dance",
            "cry",
            "laugh",
            "point",
            "sit",
            "think",
        }
        if emote not in allowed:
            outbound.append(msg(ServerMessageType.ERROR, reason="unknown emote"))
            return character_id, user_id, outbound, None
        # Soft rate limit via chat timer (social spam)
        ok_chat, retry = manager.allow_chat(character_id)
        if not ok_chat:
            outbound.append(
                msg(
                    ServerMessageType.ERROR,
                    reason="chat_rate_limit",
                    retry_after=round(retry, 3),
                )
            )
            return character_id, user_id, outbound, None
        meta = manager.get_meta(character_id)
        name = (meta or {}).get("name") or "Hero"
        emote_msg = msg(
            ServerMessageType.EMOTE,
            player_id=character_id,
            name=name,
            emote=emote,
            x=(meta or {}).get("x"),
            y=(meta or {}).get("y"),
        )
        # Peers via AOI; self via outbound (reliable single echo)
        await manager.broadcast_nearby(
            character_id, emote_msg, include_self=False, respect_ignore=True
        )
        outbound.append(emote_msg)
        return character_id, user_id, outbound, None

    # --- Use consumable (herb / wings / fairy water) ---
    if msg_type in (ClientMessageType.USE_ITEM, "use_item"):
        item_id = data.get("item") or data.get("item_id")
        if not item_id:
            outbound.append(msg(ServerMessageType.ERROR, reason="item required"))
            return character_id, user_id, outbound, None

        in_combat = combat_engine.is_in_combat(character_id)
        char = await get_character(character_id)
        if not char:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            return character_id, user_id, outbound, None

        # Combat item use is a full turn — only on hero phase
        battle = combat_engine.get(character_id) if in_combat else None
        if in_combat:
            if battle is None or battle.phase != "awaiting_hero" or battle.outcome != "ongoing":
                outbound.append(msg(ServerMessageType.ERROR, reason="wait for your turn"))
                return character_id, user_id, outbound, None

        async with db_write() as db:
            ok, reason, info = await use_consumable(
                db, char, str(item_id), in_combat=in_combat, rng=Rng()
            )
        if not ok:
            outbound.append(msg(ServerMessageType.ERROR, reason=reason))
            outbound.append(await _inventory_msg(character_id))
            return character_id, user_id, outbound, None

        # Refresh character after use
        char = await get_character(character_id) or char

        if info.get("effect") == "repel":
            manager.set_repel(character_id, int(info.get("repel_steps") or 0))

        if info.get("teleported"):
            tx, ty = int(info["x"]), int(info["y"])
            aoi_msgs = await manager.publish_move(
                character_id, tx, ty, seq=None
            )
            outbound.extend(aoi_msgs)
            try:
                tzone = zone_at(tx, ty)
            except Exception:
                tzone = None
            mok = msg(
                ServerMessageType.MOVE_OK,
                ok=True,
                x=tx,
                y=ty,
                seq=None,
                reason="wings",
            )
            if tzone:
                mok["zone"] = tzone
            outbound.append(mok)

        if in_combat and battle is not None and info.get("effect") == "heal":
            # Spend turn: heal already applied to DB — sync battle HP then enemy acts
            amount = int(info.get("amount_rolled") or info.get("healed") or 0)
            # Prefer rolled amount so battle heal matches DQ band even if already at high HP
            result = battle.act(
                {
                    "type": "item",
                    "id": str(item_id),
                    "name": info.get("name"),
                    "effect": "heal",
                    "amount": amount,
                }
            )
            # Re-sync DB HP from battle after enemy counter
            if result.get("ok"):
                patch_hp = max(0, int(battle.hero["hp"]))
                patch_mp = max(0, int(battle.hero["mp"]))
                await apply_character_patch(
                    character_id,
                    {
                        "current_hp": max(1, patch_hp) if battle.outcome == "defeat" else patch_hp,
                        "current_mp": patch_mp,
                    },
                )
            events = result.get("events") or []
            outbound.append(_combat_update(battle, events))
            if battle.outcome != "ongoing":
                char = await _persist_battle_end(character_id, battle)
                combat_engine.end(character_id)
                manager.set_in_combat(character_id, False)
                await manager.publish_status(character_id, pulse_online=True)
                end_payload = {
                    "result": battle.outcome,
                    "xp": (battle.rewards or {}).get("xp", 0),
                    "gold": (battle.rewards or {}).get("gold", 0),
                    "character": char,
                    "events": events,
                }
                if battle.outcome == "defeat":
                    end_payload["gold_lost"] = int(char.pop("gold_lost", 0) or 0)
                    end_payload["respawn"] = {"x": SPAWN_X, "y": SPAWN_Y}
                outbound.append(msg(ServerMessageType.COMBAT_END, **end_payload))
                if battle.outcome == "defeat":
                    hero = (manager.get_meta(character_id) or {}).get("name") or "Hero"
                    await manager.broadcast_nearby(
                        character_id,
                        msg(
                            ServerMessageType.CHAT,
                            player_id=character_id,
                            name="System",
                            text=f"{hero} was defeated!",
                            channel="system",
                            system=True,
                        ),
                        include_self=True,
                        respect_ignore=False,
                    )
                    aoi_msgs = await manager.publish_move(
                        character_id, SPAWN_X, SPAWN_Y, seq=None
                    )
                    outbound.extend(aoi_msgs)
                    try:
                        rzone = zone_at(SPAWN_X, SPAWN_Y)
                    except Exception:
                        rzone = "town"
                    outbound.append(
                        msg(
                            ServerMessageType.MOVE_OK,
                            ok=True,
                            x=SPAWN_X,
                            y=SPAWN_Y,
                            seq=None,
                            reason="respawn",
                            zone=rzone,
                        )
                    )
            outbound.append(
                msg(ServerMessageType.ITEM_USED, **info, in_combat=True)
            )
            outbound.append(await _inventory_msg(character_id))
            return character_id, user_id, outbound, None

        # Overworld use
        char["known_spells"] = battle_spells_at(int(char["level"]))
        char["bonuses"] = equipment_bonuses(char)
        outbound.append(msg(ServerMessageType.ITEM_USED, **info, in_combat=False))
        outbound.append(await _inventory_msg(character_id))
        return character_id, user_id, outbound, None

    # --- Town inn (rest) ---
    if msg_type in (ClientMessageType.REST, "rest", "inn"):
        if combat_engine.is_in_combat(character_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="in combat"))
            return character_id, user_id, outbound, None
        meta = manager.get_meta(character_id)
        if not meta or zone_at(int(meta["x"]), int(meta["y"])) != "town":
            outbound.append(msg(ServerMessageType.ERROR, reason="inn only in town"))
            return character_id, user_id, outbound, None
        char = await get_character(character_id)
        if not char:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            return character_id, user_id, outbound, None
        from game.item_manager import _safe_gold

        # Preview cost when asked
        if data.get("preview") or data.get("quote"):
            cost = inn_cost(char)
            full = (
                int(char.get("current_hp") or 0) >= int(char.get("max_hp") or 1)
                and int(char.get("current_mp") or 0) >= int(char.get("max_mp") or 0)
            )
            outbound.append(
                msg(
                    ServerMessageType.REST_OK,
                    preview=True,
                    cost=cost,
                    can_afford=_safe_gold(char) >= cost,
                    full=full,
                    message=(
                        "You are already well rested."
                        if full
                        else f"Inn stay costs {cost} G"
                    ),
                )
            )
            return character_id, user_id, outbound, None

        async with db_write() as db:
            ok, reason, info = await rest_at_inn(db, char)
        if not ok:
            outbound.append(msg(ServerMessageType.ERROR, reason=reason, **(info or {})))
            return character_id, user_id, outbound, None
        char = await get_character(character_id) or char
        char["known_spells"] = battle_spells_at(int(char["level"]))
        char["bonuses"] = equipment_bonuses(char)
        outbound.append(msg(ServerMessageType.REST_OK, preview=False, character=char, **info))
        return character_id, user_id, outbound, None

    # --- Inventory / shop / equip ---
    if msg_type == ClientMessageType.INVENTORY:
        outbound.append(await _inventory_msg(character_id))
        return character_id, user_id, outbound, None

    if msg_type == ClientMessageType.SHOP:
        if combat_engine.is_in_combat(character_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="in combat"))
            return character_id, user_id, outbound, None
        meta = manager.get_meta(character_id)
        # Require live presence + town (was: missing meta skipped the town check)
        if not meta or zone_at(int(meta["x"]), int(meta["y"])) != "town":
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
            return character_id, user_id, outbound, None
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
            return character_id, user_id, outbound, None
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
            ok, reason, bought = await buy_item(db, char, str(item_id or ""))
        if not ok:
            # Surface cost when short on gold (mirrors inn not-enough path)
            err = msg(ServerMessageType.ERROR, reason=reason)
            if bought.get("cost") is not None:
                err["cost"] = bought["cost"]
            if bought.get("gold") is not None:
                err["gold"] = bought["gold"]
            outbound.append(err)
            return character_id, user_id, outbound, None
        inv = await _inventory_msg(character_id)
        if bought:
            inv["bought"] = bought
            inv["message"] = (
                f"Bought {bought.get('item_name') or item_id} for {bought.get('gold_spent', 0)} G"
            )
        outbound.append(inv)
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
            ok, reason, sold = await sell_item(db, char, str(item_id or ""))
        if not ok:
            outbound.append(msg(ServerMessageType.ERROR, reason=reason))
            return character_id, user_id, outbound, None
        inv = await _inventory_msg(character_id)
        # Surface sell result so clients can toast gold earned
        if sold:
            inv["sold"] = sold
            inv["message"] = (
                f"Sold {sold.get('item_name') or item_id} for {sold.get('gold_gained', 0)} G"
            )
        outbound.append(inv)
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
        try:
            battle = combat_engine.start(character_id, char, str(enemy_id), seed=seed)
        except RuntimeError:
            outbound.append(msg(ServerMessageType.ERROR, reason="already in combat"))
            return character_id, user_id, outbound, None
        manager.set_in_combat(character_id, True)
        await manager.publish_status(character_id, pulse_online=True)
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
