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
    discard_item,
    equip_item,
    equipment_bonuses,
    list_items,
    resolve_item_id,
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


def _format_uptime(seconds: int) -> str:
    """Human-readable uptime for /time (e.g. 1h 02m 03s)."""
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {sec:02d}s"
    if m:
        return f"{m}m {sec:02d}s"
    return f"{sec}s"


def _afk_snap(meta: dict[str, Any] | None) -> tuple[bool, str | None]:
    """Capture manual AFK + status before allow_chat (which clears AFK).

    Used so failed private delivery can refund_chat(..., restore_afk=True)
    and keep census / badges honest after a multiplayer send race.
    """
    if not meta:
        return False, None
    was = bool(meta.get("afk"))
    msg_txt: str | None = None
    if was:
        am = meta.get("afk_message")
        if isinstance(am, str) and am.strip():
            msg_txt = am.strip()[:48]
    return was, msg_txt


def _parse_positive_qty(raw: Any) -> int | None:
    """Parse buy/sell/discard quantity. Returns int >= 1 or None if invalid.

    Rejects bools and non-integer floats (2.5 must not silently become 2).
    Digit strings like \"2\" are accepted.
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw >= 1 else None
    if isinstance(raw, float):
        if not math.isfinite(raw) or not raw.is_integer():
            return None
        q = int(raw)
        return q if q >= 1 else None
    if isinstance(raw, str):
        s = raw.strip()
        if not s or not s.lstrip("-").isdigit():
            return None
        try:
            q = int(s)
        except ValueError:
            return None
        return q if q >= 1 else None
    return None


async def _inventory_msg(character_id: int) -> dict:
    from game.item_manager import MAX_BAG_SLOTS, MAX_STACK_QTY

    db = await get_db()
    char = await get_character(character_id)
    items = await list_items(db, character_id)
    if char:
        char["known_spells"] = battle_spells_at(int(char["level"]))
        char["field_spells"] = field_spells_at(int(char["level"]))
        char = character_public(char, items)
    # Bag caps for client UI (distinct stacks / per-stack max)
    bag = {
        "used": len(items),
        "max_slots": MAX_BAG_SLOTS,
        "max_stack": MAX_STACK_QTY,
    }
    return msg(
        ServerMessageType.INVENTORY_UPDATE,
        items=items,
        character=char,
        bag=bag,
    )


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


def _resolve_item_arg(raw: Any) -> tuple[str | None, str | None]:
    """Resolve slash/UI item text → canonical id (or error reason)."""
    return resolve_item_id(raw)


async def _announce_combat_outcome(character_id: int, outcome: str) -> None:
    """Nearby multiplayer system line for combat result (victory / fled / defeat)."""
    hero = (manager.get_meta(character_id) or {}).get("name") or "Hero"
    if outcome == "defeat":
        text = f"{hero} was defeated!"
        include_self = True
    elif outcome == "victory":
        text = f"{hero} was victorious!"
        include_self = False
    elif outcome == "fled":
        text = f"{hero} fled battle!"
        include_self = False
    else:
        return
    await manager.broadcast_nearby(
        character_id,
        msg(
            ServerMessageType.CHAT,
            player_id=character_id,
            name="System",
            text=text,
            channel="system",
            system=True,
        ),
        include_self=include_self,
        respect_ignore=False,
    )


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
        from config import PROCESS_STARTED_AT, VERSION as _VER

        pong_body: dict[str, Any] = {
            "t": client_t,
            "server_t": _time.time(),
            "online": len(manager.online_ids()),
            "afk_count": manager.afk_count(),
            "combat_count": manager.combat_count(),
            "zones": manager.zone_counts(),
            "version": _VER,
            "uptime": max(0, int(_time.time() - PROCESS_STARTED_AT)),
        }
        if character_id is not None:
            pong_body["nearby_count"] = len(manager.ids_nearby(character_id))
            pong_body["nearby_afk"] = manager.nearby_afk_count(character_id)
            pong_body["nearby_combat"] = manager.nearby_combat_count(character_id)
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
        nearby_list = nearby
        ignores_snap = manager.ignore_list(character_id)
        lw_id, lw_name = manager.last_whisper_from(character_id)
        last_whisper = None
        if lw_id is not None or lw_name:
            last_whisper = {"id": lw_id, "name": lw_name}
        from network.websocket_manager import _is_idle as _idle_chk

        you_blob = None
        if meta is not None:
            you_blob = {
                "x": meta["x"],
                "y": meta["y"],
                "zone": sync_zone,
                "session_id": manager.session_id(character_id),
                "afk": bool(meta.get("afk")),
                "idle": _idle_chk(meta),
                "in_combat": bool(meta.get("in_combat")),
            }
            if you_blob["afk"]:
                am = meta.get("afk_message")
                if isinstance(am, str) and am.strip():
                    you_blob["afk_message"] = am.strip()[:48]
        outbound.append(
            msg(
                ServerMessageType.WORLD_STATE,
                players=nearby_list,
                enemies=[],
                map=map_payload(),
                online=len(manager.online_ids()),
                afk_count=manager.afk_count(),
                nearby_count=len(nearby_list),
                nearby_afk=manager.nearby_afk_count(character_id),
                nearby_combat=manager.nearby_combat_count(character_id),
                zones=manager.zone_counts(),
                roster=manager.online_roster(),
                you=you_blob,
                repel=manager.repel_remaining(character_id),
                radiant=manager.radiant_remaining(character_id),
                zone=sync_zone,
                session_id=manager.session_id(character_id),
                # Rehydrate multiplayer soft-state without full reconnect
                ignores=ignores_snap,
                last_whisper=last_whisper,
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
                afk_count=manager.afk_count(),
                combat_count=manager.combat_count(),
                nearby_afk=manager.nearby_afk_count(character_id),
                nearby_combat=manager.nearby_combat_count(character_id),
                you={
                    "id": character_id,
                    "name": (meta or {}).get("name"),
                    "level": (meta or {}).get("level"),
                    "x": meta["x"] if meta else None,
                    "y": meta["y"] if meta else None,
                    "in_combat": bool(meta.get("in_combat")) if meta else False,
                    "idle": _is_idle(meta) if meta else False,
                    "afk": bool((meta or {}).get("afk")),
                    "session_id": manager.session_id(character_id),
                    "repel": manager.repel_remaining(character_id),
                    "radiant": manager.radiant_remaining(character_id),
                    "zone": you_zone,
                },
            )
        )
        # Optional AFK reason on self card
        who_msg = outbound[-1]
        you_card = who_msg.get("you") if isinstance(who_msg, dict) else None
        if (
            isinstance(you_card, dict)
            and you_card.get("afk")
            and meta is not None
        ):
            am = meta.get("afk_message")
            if isinstance(am, str) and am.strip():
                you_card["afk_message"] = am.strip()[:48]
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
        nearby_afk = manager.nearby_afk_count(character_id)
        nearby_combat = manager.nearby_combat_count(character_id)
        afk_n = manager.afk_count()
        near_body = {
            "type": "near",
            "players": nearby,
            "nearby_count": len(nearby),
            "nearby_afk": nearby_afk,
            "nearby_combat": nearby_combat,
            "afk_count": afk_n,
            "online": len(manager.online_ids()),
            "zone": you_zone,
            "zones": manager.zone_counts(),
            "message": (
                f"{len(nearby)} nearby · combat {nearby_combat} · "
                f"AFK {nearby_afk} · {afk_n} AFK online"
            ),
        }
        you_afk = bool((meta or {}).get("afk"))
        near_body["you"] = {
            "id": character_id,
            "name": (meta or {}).get("name"),
            "afk": you_afk,
            "zone": you_zone,
            "session_id": manager.session_id(character_id),
        }
        if you_afk and meta is not None:
            am = meta.get("afk_message")
            if isinstance(am, str) and am.strip():
                near_body["you"]["afk_message"] = am.strip()[:48]
        outbound.append(near_body)
        return character_id, user_id, outbound, None

    # --- Lightweight census (online + zone counts, no full roster) ---
    if msg_type in ("counts", "census", "population"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        zones = manager.zone_counts()
        online_n = len(manager.online_ids())
        nearby_n = len(manager.ids_nearby(character_id))
        sid = manager.session_id(character_id)
        meta = manager.get_meta(character_id)
        from network.websocket_manager import _is_idle as _idle_chk
        from game.world_manager import zone_at as _z_at

        you_zone = None
        if meta is not None:
            try:
                you_zone = _z_at(int(meta["x"]), int(meta["y"]))
            except Exception:
                you_zone = None
        played_sec = 0
        if meta is not None:
            import time as _time

            try:
                started = float(meta.get("session_started") or 0.0)
                if started > 0:
                    played_sec = max(0, int(_time.monotonic() - started))
            except (TypeError, ValueError):
                played_sec = 0
        you_afk = bool((meta or {}).get("afk"))
        you = {
            "id": character_id,
            "name": (meta or {}).get("name"),
            "nearby_count": nearby_n,
            "afk": you_afk,
            "idle": _idle_chk(meta) if meta else False,
            "zone": you_zone,
            "in_combat": bool((meta or {}).get("in_combat")),
            "played": played_sec,
        }
        if you_afk and meta is not None:
            try:
                import time as _time

                since = float(meta.get("afk_since") or 0.0)
                if since > 0:
                    you["afk_for"] = max(0, int(_time.monotonic() - since))
            except (TypeError, ValueError):
                pass
            am = meta.get("afk_message")
            if isinstance(am, str) and am.strip():
                you["afk_message"] = am.strip()[:48]
        if sid is not None:
            you["session_id"] = sid
        afk_n = manager.afk_count()
        combat_n = manager.combat_count()
        nearby_combat = manager.nearby_combat_count(character_id)
        body = {
            "type": "counts",
            "online": online_n,
            "afk_count": afk_n,
            "combat_count": combat_n,
            "nearby_count": nearby_n,
            "nearby_combat": nearby_combat,
            "zones": zones,
            "you": you,
            "session_id": sid,
            "message": (
                f"{online_n} online · AFK {afk_n} · fighting {combat_n} · "
                f"nearby {nearby_n} · near combat {nearby_combat} · "
                f"town {zones.get('town', 0)} · field {zones.get('field', 0)} · "
                f"dungeon {zones.get('dungeon', 0)}"
            ),
        }
        outbound.append(body)
        return character_id, user_id, outbound, None

    # --- Where am I / zone population (multiplayer social) ---
    if msg_type in (
        "zone",
        "where",
        "area",
        "whereami",
        "coords",
        "pos",
        "position",
        "mapinfo",
    ):
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
        zone_afk = manager.zone_afk_count(character_id, include_self=True)
        zone_combat = manager.zone_combat_count(character_id, include_self=True)
        afk_n = manager.afk_count()
        zone_body = {
            "type": "zone",
            "zone": you_zone,
            "x": x,
            "y": y,
            "zones": zones,
            "players": mates,
            "zone_count": len(mates),
            "zone_afk": zone_afk,
            "zone_combat": zone_combat,
            "afk_count": afk_n,
            "population": zone_pop,
            "online": len(manager.online_ids()),
            "message": (
                f"You are in the {you_zone} ({len(mates)} here · AFK {zone_afk}"
                f" · combat {zone_combat})."
                if you_zone in ("town", "field", "dungeon")
                else "You are somewhere on the map."
            ),
        }
        sid_z = manager.session_id(character_id)
        if sid_z is not None:
            zone_body["session_id"] = sid_z
        outbound.append(zone_body)
        return character_id, user_id, outbound, None

    # --- Look / examine / inspect / profile / whereis (public card; coords if nearby) ---
    if msg_type in (
        ClientMessageType.LOOK,
        ClientMessageType.EXAMINE,
        "look",
        "examine",
        "inspect",
        "profile",
        "card",
        "player_info",
        "whereis",
        "where_is",
    ):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        target_name = data.get("name") or data.get("to") or data.get("target") or data.get("player")
        raw_pid = data.get("player_id") if data.get("player_id") is not None else data.get("id")
        tid: int | None = None
        had_raw_pid = raw_pid is not None
        if had_raw_pid:
            from network.websocket_manager import coerce_character_id

            tid = coerce_character_id(raw_pid)
            # Explicit but invalid id (bool/float/garbage) → not found, not bare-self
            if tid is None:
                outbound.append(msg(ServerMessageType.ERROR, reason="player not found"))
                return character_id, user_id, outbound, None
        if tid is None and isinstance(target_name, str) and target_name.strip():
            tid, nerr = manager.resolve_live_name(target_name)
            if nerr == "name ambiguous":
                outbound.append(msg(ServerMessageType.ERROR, reason="name ambiguous"))
                return character_id, user_id, outbound, None
            if tid is None and nerr == "player not online":
                # Named target resolved to nobody live — not "not found" (typo vs offline)
                outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
                return character_id, user_id, outbound, None
        # Bare look / empty name → examine self (MVP social convenience)
        if tid is None and not had_raw_pid and (
            target_name is None
            or (isinstance(target_name, str) and not target_name.strip())
        ):
            tid = character_id
        if tid is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="player not found"))
            return character_id, user_id, outbound, None
        tmeta = manager.get_meta(tid)
        if tmeta is None or tid not in manager.online_ids():
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
            "afk": bool(tmeta.get("afk")),
        }
        # Zone type is OK without coords (same privacy model as who/find)
        try:
            tz = zone_at(int(tmeta["x"]), int(tmeta["y"]))
            if tz in ("town", "field", "dungeon"):
                card["zone"] = tz
        except Exception:
            pass
        if is_near:
            card["x"] = tmeta.get("x")
            card["y"] = tmeta.get("y")
            card["map_id"] = tmeta.get("map_id")
        # Soft AFK flag (no coords when far)
        try:
            from network.websocket_manager import _is_idle
            import time as _time

            card["idle"] = _is_idle(tmeta)
            if card["afk"]:
                since = float(tmeta.get("afk_since") or 0.0)
                if since > 0:
                    card["afk_for"] = max(0, int(_time.monotonic() - since))
                am = tmeta.get("afk_message")
                if isinstance(am, str) and am.strip():
                    card["afk_message"] = am.strip()[:48]
        except Exception:
            card["idle"] = False
        sid = tmeta.get("session_id")
        if sid is not None:
            card["session_id"] = sid
        outbound.append(msg(ServerMessageType.LOOK, player=card))
        return character_id, user_id, outbound, None

    # --- Self status (lightweight sheet; no inventory dump) ---
    if msg_type in (
        ClientMessageType.STATUS,
        ClientMessageType.ME,
        "status",
        "me",
        "whoami",
        "stats",
        "sheet",
    ):
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
        from network.websocket_manager import _is_idle as _idle_chk

        you_afk = bool(meta.get("afk")) if meta else False
        you_idle = _idle_chk(meta) if meta else False
        you_status: dict = {
            "x": x,
            "y": y,
            "zone": z,
            "in_combat": combat_engine.is_in_combat(character_id),
            "repel": manager.repel_remaining(character_id),
            "radiant": manager.radiant_remaining(character_id),
            "session_id": manager.session_id(character_id),
            "afk": you_afk,
            "idle": you_idle,
        }
        if you_afk and meta is not None:
            am = meta.get("afk_message")
            if isinstance(am, str) and am.strip():
                you_status["afk_message"] = am.strip()[:48]
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
                you=you_status,
                online=len(manager.online_ids()),
                afk_count=manager.afk_count(),
            )
        )
        return character_id, user_id, outbound, None

    # --- Gold only (lightweight wallet peek) ---
    if msg_type in ("gold", "money", "wallet"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        char = await get_character(character_id)
        if not char:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            return character_id, user_id, outbound, None
        gold = char.get("gold")
        outbound.append(
            msg(
                "gold",
                gold=gold,
                message=f"You have {gold} G.",
            )
        )
        return character_id, user_id, outbound, None

    # --- HP / MP vitals peek ---
    if msg_type in ("hp", "mp", "vitals", "life"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        char = await get_character(character_id)
        if not char:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            return character_id, user_id, outbound, None
        # Prefer live combat HP/MP when fighting
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
        outbound.append(
            msg(
                "vitals",
                hp=chp,
                max_hp=mhp,
                mp=cmp_,
                max_mp=mmp,
                in_combat=bool(
                    battle is not None and battle.outcome == "ongoing"
                ),
                message=f"HP {chp}/{mhp} · MP {cmp_}/{mmp}",
            )
        )
        return character_id, user_id, outbound, None

    # --- Level / XP peek ---
    if msg_type in ("xp", "exp", "level", "experience"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        char = await get_character(character_id)
        if not char:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            return character_id, user_id, outbound, None
        from game.progression import xp_to_next_level

        lvl = int(char.get("level") or 1)
        xp = int(char.get("experience") or 0)
        xp_prog = xp_to_next_level(xp, lvl)
        to_next = xp_prog.get("xp_to_next")
        outbound.append(
            msg(
                "xp",
                level=lvl,
                experience=xp,
                xp_progress=xp_prog,
                message=(
                    f"Level {lvl} · {xp} XP"
                    + (
                        f" · {to_next} to next"
                        if to_next is not None and not xp_prog.get("max_level")
                        else ""
                    )
                ),
            )
        )
        return character_id, user_id, outbound, None

    # --- Spells list (battle + field known at current level) ---
    if msg_type in ("spells", "magic", "spell_list"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        char = await get_character(character_id)
        if not char:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            return character_id, user_id, outbound, None
        lvl = int(char.get("level") or 1)
        battle = battle_spells_at(lvl)
        field = field_spells_at(lvl)
        outbound.append(
            msg(
                "spells",
                battle=battle,
                field=field,
                level=lvl,
                message=(
                    f"Battle: {', '.join(battle) or 'none'} · "
                    f"Field: {', '.join(field) or 'none'}"
                ),
            )
        )
        return character_id, user_id, outbound, None

    # --- Active buffs / effects (repel, radiant, combat, AFK) ---
    if msg_type in ("buffs", "effects", "debuffs", "status_effects"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        meta = manager.get_meta(character_id)
        repel = manager.repel_remaining(character_id)
        radiant = manager.radiant_remaining(character_id)
        in_combat = combat_engine.is_in_combat(character_id)
        afk = bool(meta.get("afk")) if meta else False
        from network.websocket_manager import _is_idle as _idle_chk
        import time as _time

        idle = _idle_chk(meta) if meta else False
        afk_for = None
        if afk and meta is not None:
            try:
                since = float(meta.get("afk_since") or 0.0)
                if since > 0:
                    afk_for = max(0, int(_time.monotonic() - since))
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
        body = {
            "type": "buffs",
            "repel": repel,
            "radiant": radiant,
            "in_combat": in_combat,
            "afk": afk,
            "idle": idle,
            "session_id": manager.session_id(character_id),
            "message": (" · ".join(bits) if bits else "No active buffs."),
        }
        if afk_for is not None:
            body["afk_for"] = afk_for
        if afk_reason:
            body["afk_message"] = afk_reason
        outbound.append(body)
        return character_id, user_id, outbound, None

    # --- Controls / keybinds summary (client HUD helper) ---
    if msg_type in ("keys", "controls", "keybinds", "keymap"):
        if character_id is not None:
            manager.touch(character_id)
        outbound.append(
            msg(
                "controls",
                overworld=[
                    "WASD move",
                    "T global chat · Y nearby",
                    "E emote · F status · L look · O who",
                    "I bag · R inn · H/M field magic · K spells",
                    "Esc disconnect",
                ],
                combat=["↑↓ menu · Enter", "1–9 jump", "A attack · F flee · H herb"],
                inventory=["Enter use/equip", "S sell · D discard · U unequip · Tab shop"],
                slash=[
                    "/w /r /last · /say /g /z /yell · /find · /who /near /zone",
                    "/hp /xp /gold /spells /bag /buffs /played · /stuck /afk /quit",
                ],
                message=(
                    "WASD · T/Y chat · E emote · F status · L look · "
                    "R inn · I bag · H/M magic · O who · /stuck · Esc"
                ),
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
                    {"cmd": "whisper", "hint": "/w Name message (unique prefix OK)"},
                    {"cmd": "say", "hint": "/say · /s message — nearby chat"},
                    {"cmd": "find", "hint": "/find Name · zone:town · afk:yes · combat:yes · idle:yes"},
                    {"cmd": "status", "hint": "F or /status · /me · /whoami · /stats"},
                    {"cmd": "look", "hint": "L · /look · /inspect · /profile · /whereis"},
                    {"cmd": "who", "hint": "O · /who · /players — online + zone counts"},
                    {"cmd": "near", "hint": "/near · /here — nearby heroes only"},
                    {"cmd": "zone", "hint": "/zone · /where · /mapinfo · /coords"},
                    {"cmd": "counts", "hint": "/counts · /census — online + you + zones"},
                    {"cmd": "emote", "hint": "E · /wave · /bow Name · /wave @last — emote shortcuts"},
                    {"cmd": "lastemote", "hint": "/lastemote — last directed emote target"},
                    {"cmd": "busy", "hint": "/busy [reason] — AFK alias"},
                    {"cmd": "invite", "hint": "/invite Name · /meet @last — meetup invite"},
                    {"cmd": "cancel", "hint": "/cancel · /uninvite — cancel your last invite"},
                    {"cmd": "accept", "hint": "/accept · /coming — reply to last invite"},
                    {"cmd": "decline", "hint": "/decline · /later — decline last invite"},
                    {"cmd": "lastinvite", "hint": "/lastinvite — who invited you last"},
                    {"cmd": "share", "hint": "/share Name — privately share your zone + coords"},
                    {"cmd": "poke", "hint": "/poke Name · /nudge @last — get their attention"},
                    {"cmd": "askwhere", "hint": "/askwhere Name · /locate @last — ask them to /share"},
                    {"cmd": "fighting", "hint": "/fighting · /combats — nearby heroes in combat"},
                    {"cmd": "yell", "hint": "/yell · /shout · /z — zone chat"},
                    {"cmd": "stuck", "hint": "/stuck · /unstuck · /home — return to town"},
                    {"cmd": "use", "hint": "/use herb — use consumable from bag"},
                    {"cmd": "buy", "hint": "/buy copper sword [qty] — names or ids OK"},
                    {"cmd": "sell", "hint": "/sell herb [qty] — names or ids OK"},
                    {"cmd": "equip", "hint": "/equip copper sword — name/id, slot auto"},
                    {"cmd": "rest", "hint": "R — inn quote, R again to stay (town)"},
                    {"cmd": "inventory", "hint": "I · /bag · /inv — bag (12 stacks · max 8)"},
                    {"cmd": "gold", "hint": "/gold · /money — wallet peek"},
                    {"cmd": "hp", "hint": "/hp · /vitals — HP/MP peek"},
                    {"cmd": "xp", "hint": "/xp · /level — level + XP to next"},
                    {"cmd": "buffs", "hint": "/buffs · /effects — repel · radiant · AFK"},
                    {"cmd": "played", "hint": "/played · /session — this connection length"},
                    {"cmd": "keys", "hint": "/keys · /controls — keybind summary"},
                    {"cmd": "spells", "hint": "/spells · /magic — known battle + field"},
                    {"cmd": "unequip", "hint": "/unequip weapon|armor|shield|helmet"},
                    {"cmd": "discard", "hint": "/discard herb [qty] · D in bag — free a slot"},
                    {"cmd": "cast", "hint": "/cast heal · /repel · /return · H/M keys"},
                    {"cmd": "combat", "hint": "1–9 menu · A attack · F flee · H herb"},
                    {"cmd": "ignore", "hint": "/ignore · /unignore · /ignores · /blocklist"},
                    {"cmd": "reply", "hint": "/r message — reply last whisper (server-tracked)"},
                    {"cmd": "lastwhisper", "hint": "/last · /lastwhisper — who /r targets"},
                    {"cmd": "roll", "hint": "/roll · /dice — 1d100 nearby"},
                    {"cmd": "version", "hint": "/version · /server · /info — server version"},
                    {"cmd": "time", "hint": "/time · /uptime — server clock + uptime"},
                    {"cmd": "motd", "hint": "/motd — message of the day"},
                    {"cmd": "afk", "hint": "/afk [reason] · /away · /back — AFK badge + status"},
                    {"cmd": "block", "hint": "/block · /unblock — same as ignore"},
                    {"cmd": "quit", "hint": "/quit · /logout — leave the world"},
                ],
                channels=["global", "nearby", "zone", "whisper"],
                version=__import__("config", fromlist=["VERSION"]).VERSION,
                online=len(manager.online_ids()),
            )
        )
        return character_id, user_id, outbound, None

    # --- MOTD (multiplayer welcome blurb) ---
    if msg_type in ("motd", "message_of_the_day", "rules"):
        from config import MOTD, PROCESS_STARTED_AT, VERSION as _VER
        import time as _time

        if character_id is not None:
            manager.touch(character_id)
        outbound.append(
            msg(
                "motd",
                text=str(MOTD)[:500],
                version=_VER,
                online=len(manager.online_ids()),
                afk_count=manager.afk_count(),
                zones=manager.zone_counts(),
                uptime=max(0, int(_time.time() - PROCESS_STARTED_AT)),
            )
        )
        return character_id, user_id, outbound, None

    # --- Manual AFK / away / busy / back (+ optional status message) ---
    if msg_type in ("afk", "away", "busy", "back"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        want_afk = msg_type in ("afk", "away", "busy")
        if msg_type == "back":
            want_afk = False
        if msg_type in ("afk", "busy") and (data.get("clear") or data.get("off")):
            want_afk = False
        # Only real strings become AFK reasons — never str(True)/str(123)
        raw_afk_text = ""
        for _k in ("text", "message", "reason", "status", "mode"):
            _v = data.get(_k)
            if isinstance(_v, str) and _v.strip():
                raw_afk_text = _v.strip()
                break
        # /afk with text "back" or explicit back
        if msg_type in ("afk", "away", "busy") and raw_afk_text.lower() in (
            "back",
            "off",
            "clear",
            "0",
            "false",
        ):
            want_afk = False
            raw_afk_text = ""
        meta_pre = manager.get_meta(character_id)
        was_afk = bool((meta_pre or {}).get("afk"))
        afk_msg_arg: str | None = None
        if want_afk:
            # Empty → no reason; non-empty → set/sanitize (sanitize rejects non-str)
            afk_msg_arg = raw_afk_text if raw_afk_text else None
        if not manager.set_afk(character_id, want_afk, message=afk_msg_arg):
            outbound.append(msg(ServerMessageType.ERROR, reason="not online"))
            return character_id, user_id, outbound, None
        if not want_afk:
            manager.touch(character_id)
        await manager.publish_status(character_id, pulse_online=True)
        meta = manager.get_meta(character_id)
        from network.websocket_manager import _is_idle as _idle_chk

        # Nearby system notice when AFK state flips (multiplayer roster hygiene)
        if want_afk != was_afk and meta is not None:
            pname = (meta.get("name") or "Hero")
            reason = meta.get("afk_message") if want_afk else None
            if want_afk and isinstance(reason, str) and reason.strip():
                notice_text = f"{pname} is now AFK: {reason.strip()[:48]}."
            elif want_afk:
                notice_text = f"{pname} is now AFK."
            else:
                notice_text = f"{pname} is back."
            notice = msg(
                ServerMessageType.CHAT,
                player_id=character_id,
                name="System",
                text=notice_text,
                channel="system",
                system=True,
            )
            sid_a = manager.session_id(character_id)
            if sid_a is not None:
                notice["session_id"] = sid_a
            await manager.broadcast_nearby(
                character_id, notice, include_self=False, respect_ignore=False
            )

        ack_reason = None
        if want_afk and meta is not None:
            am = meta.get("afk_message")
            if isinstance(am, str) and am.strip():
                ack_reason = am.strip()[:48]
        ack_body: dict = {
            "type": "afk",
            "afk": want_afk,
            "idle": _idle_chk(meta) if meta else want_afk,
            "session_id": manager.session_id(character_id),
            "message": (
                (f"You are now AFK: {ack_reason}." if ack_reason else "You are now AFK.")
                if want_afk
                else "Welcome back."
            ),
        }
        if ack_reason:
            ack_body["afk_message"] = ack_reason
        outbound.append(ack_body)
        return character_id, user_id, outbound, None

    # --- Last whisper peer (multiplayer /r target after soft reconnect) ---
    if msg_type in (
        "lastwhisper",
        "last_whisper",
        "last",
        "reply_to",
        "who_last",
    ):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        lid, lname = manager.last_whisper_from(character_id)
        peer = None
        online = False
        peer_afk = False
        if lid is not None:
            online = manager.is_online(lid)
            pmeta = manager.get_meta(lid) if online else None
            peer_afk = bool(pmeta.get("afk")) if pmeta else False
            peer = {
                "id": lid,
                "name": lname or (pmeta or {}).get("name"),
                "online": online,
                "afk": peer_afk,
            }
            psid = (pmeta or {}).get("session_id") if pmeta else None
            if psid is not None:
                peer["session_id"] = psid
            if peer_afk and pmeta is not None:
                pam = pmeta.get("afk_message")
                if isinstance(pam, str) and pam.strip():
                    peer["afk_message"] = pam.strip()[:48]
        outbound.append(
            msg(
                "lastwhisper",
                peer=peer,
                online=online,
                message=(
                    f"Last whisper: {peer['name']}"
                    + (" (online)" if online else " (offline)" if peer else "")
                    if peer
                    else "No one to reply to yet."
                ),
            )
        )
        return character_id, user_id, outbound, None

    # --- Last directed-emote peer (multiplayer /wave @last) ---
    if msg_type in ("lastemote", "last_emote", "who_emote", "emote_last"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        lid, lname = manager.last_emote_to(character_id)
        peer = None
        online = False
        peer_afk = False
        if lid is not None:
            online = manager.is_online(lid)
            pmeta = manager.get_meta(lid) if online else None
            peer_afk = bool(pmeta.get("afk")) if pmeta else False
            peer = {
                "id": lid,
                "name": lname or (pmeta or {}).get("name"),
                "online": online,
                "afk": peer_afk,
            }
            psid = (pmeta or {}).get("session_id") if pmeta else None
            if psid is not None:
                peer["session_id"] = psid
            if peer_afk and pmeta is not None:
                pam = pmeta.get("afk_message")
                if isinstance(pam, str) and pam.strip():
                    peer["afk_message"] = pam.strip()[:48]
        outbound.append(
            msg(
                "lastemote",
                peer=peer,
                online=online,
                message=(
                    f"Last emote: {peer['name']}"
                    + (" (online)" if online else " (offline)" if peer else "")
                    if peer
                    else "No directed emote target yet."
                ),
            )
        )
        return character_id, user_id, outbound, None

    # --- Meetup invite (lightweight multiplayer social — not a party) ---
    if msg_type in ("invite", "meet", "beckon", "come"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        target_name = data.get("to") or data.get("name") or data.get("target") or data.get("player")
        want_last = bool(data.get("reply")) or (
            isinstance(target_name, str)
            and target_name.strip().lower() in ("@last", "last", "!")
        )
        raw_pid = None
        if data.get("to_id") is not None:
            raw_pid = data.get("to_id")
        elif data.get("player_id") is not None:
            raw_pid = data.get("player_id")
        target_id = (
            manager.find_id_by_player_id(raw_pid) if raw_pid is not None else None
        )
        if raw_pid is not None and target_id is None:
            from network.websocket_manager import coerce_character_id

            if coerce_character_id(raw_pid) is None:
                outbound.append(msg(ServerMessageType.ERROR, reason="player not found"))
            else:
                outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        if want_last and target_id is None:
            # Prefer last whisper peer, else last directed-emote target
            lid, lname = manager.last_whisper_from(character_id)
            if lid is None:
                lid, lname = manager.last_emote_to(character_id)
            if lid is None:
                outbound.append(msg(ServerMessageType.ERROR, reason="no one to invite"))
                return character_id, user_id, outbound, None
            target_id = lid
            target_name = lname
        if target_id is None and isinstance(target_name, str) and target_name.strip():
            if not want_last:
                tid, nerr = manager.resolve_live_name(target_name)
                if nerr == "name ambiguous":
                    outbound.append(msg(ServerMessageType.ERROR, reason="name ambiguous"))
                    return character_id, user_id, outbound, None
                target_id = tid
        if target_id is None:
            if not (
                isinstance(target_name, str) and target_name.strip()
            ) and raw_pid is None and not want_last:
                outbound.append(msg(ServerMessageType.ERROR, reason="invite target required"))
            else:
                outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        if target_id == character_id:
            outbound.append(msg(ServerMessageType.ERROR, reason="cannot invite yourself"))
            return character_id, user_id, outbound, None
        if target_id not in manager.online_ids():
            outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        if manager.is_ignored_by(target_id, character_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="player unavailable"))
            return character_id, user_id, outbound, None
        if manager.is_ignored_by(character_id, target_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="you ignore that player"))
            return character_id, user_id, outbound, None
        meta_pre = manager.get_meta(character_id)
        from network.websocket_manager import _is_idle as _idle_chk

        was_idle = _idle_chk(meta_pre) if meta_pre else False
        was_afk, afk_msg_snap = _afk_snap(meta_pre)
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
        tmeta = manager.get_meta(target_id)
        name = (meta or {}).get("name") or "Hero"
        tname = (tmeta or {}).get("name") or (
            target_name.strip() if isinstance(target_name, str) else "Hero"
        )
        you_zone = None
        you_x = you_y = None
        if meta is not None:
            try:
                you_x, you_y = int(meta["x"]), int(meta["y"])
                you_zone = zone_at(you_x, you_y)
            except Exception:
                you_zone = None
        zone_bit = (
            f" in the {you_zone}"
            if you_zone in ("town", "field", "dungeon")
            else " on the map"
        )
        invite_line = f"{name} invites you to meet them{zone_bit}."
        invite_msg: dict = {
            "type": "invite",
            "from": name,
            "from_id": character_id,
            "to": tname,
            "to_id": target_id,
            "message": invite_line,
            "zone": you_zone,
        }
        # Share coords only when already nearby (same privacy model as look)
        if target_id in set(manager.ids_nearby(character_id)):
            invite_msg["x"] = you_x
            invite_msg["y"] = you_y
            invite_msg["nearby"] = True
        else:
            invite_msg["nearby"] = False
        sid_i = manager.session_id(character_id)
        if sid_i is not None:
            invite_msg["session_id"] = sid_i
        delivered = await manager.send(target_id, invite_msg)
        if not delivered:
            manager.refund_chat(
                character_id, restore_afk=was_afk, afk_message=afk_msg_snap
            )
            outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        # Remember as social peer for /r and /invite @last
        manager.note_whisper_from(character_id, target_id, tname)
        # Target remembers inviter for /accept · /lastinvite (soft-grace)
        manager.note_invite_from(target_id, character_id, name)
        # Inviter remembers target for /cancel
        manager.note_invite_to(character_id, target_id, tname)
        echo = dict(invite_msg)
        echo["message"] = f"Invite sent to {tname}."
        target_afk = bool((tmeta or {}).get("afk"))
        if target_afk:
            echo["target_afk"] = True
            am = (tmeta or {}).get("afk_message")
            if isinstance(am, str) and am.strip():
                echo["target_afk_message"] = am.strip()[:48]
        outbound.append(echo)
        if was_idle:
            await manager.publish_status(character_id)
        return character_id, user_id, outbound, None

    # --- Cancel last outgoing meetup invite ---
    if msg_type in ("cancel", "uninvite", "invite_cancel", "revoke_invite"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        tid, tname = manager.last_invite_to(character_id)
        if tid is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="no invite to cancel"))
            return character_id, user_id, outbound, None
        meta_pre = manager.get_meta(character_id)
        from network.websocket_manager import _is_idle as _idle_chk

        was_idle = _idle_chk(meta_pre) if meta_pre else False
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
        live_name = tname
        notified = False
        if tid in manager.online_ids():
            tmeta = manager.get_meta(tid)
            live_name = (tmeta or {}).get("name") or tname or "Hero"
            # Only notify + clear if invite is still pending from us
            # (prevents spam cancel after accept/decline)
            from_id, _ = manager.last_invite_from(tid)
            if from_id == character_id:
                manager.clear_last_invite(tid)
                cancel_msg = {
                    "type": "invite_cancel",
                    "from": name,
                    "from_id": character_id,
                    "to": live_name,
                    "to_id": tid,
                    "message": f"{name} cancelled their meetup invite.",
                }
                sid_c = manager.session_id(character_id)
                if sid_c is not None:
                    cancel_msg["session_id"] = sid_c
                await manager.send(tid, cancel_msg)
                notified = True
        manager.clear_last_invite_to(character_id)
        outbound.append(
            msg(
                "invite_cancel",
                action="cancel",
                to=live_name,
                to_id=tid,
                notified=notified,
                message=(
                    f"Invite to {live_name} cancelled."
                    if notified
                    else f"Cleared invite to {live_name} (already answered or offline)."
                ),
            )
        )
        if was_idle:
            await manager.publish_status(character_id)
        return character_id, user_id, outbound, None

    # --- Private location share (meetup helper — always opt-in) ---
    if msg_type in ("share", "sharepos", "share_pos", "whereami_share", "here_i_am"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        target_name = data.get("to") or data.get("name") or data.get("target") or data.get("player")
        want_last = bool(data.get("reply")) or (
            isinstance(target_name, str)
            and target_name.strip().lower() in ("@last", "last", "!")
        )
        raw_pid = None
        if data.get("to_id") is not None:
            raw_pid = data.get("to_id")
        elif data.get("player_id") is not None:
            raw_pid = data.get("player_id")
        target_id = (
            manager.find_id_by_player_id(raw_pid) if raw_pid is not None else None
        )
        if raw_pid is not None and target_id is None:
            from network.websocket_manager import coerce_character_id

            if coerce_character_id(raw_pid) is None:
                outbound.append(msg(ServerMessageType.ERROR, reason="player not found"))
            else:
                outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        if want_last and target_id is None:
            lid, lname = manager.last_whisper_from(character_id)
            if lid is None:
                lid, lname = manager.last_emote_to(character_id)
            if lid is None:
                lid, lname = manager.last_invite_to(character_id)
            if lid is None:
                lid, lname = manager.last_invite_from(character_id)
            if lid is None:
                outbound.append(msg(ServerMessageType.ERROR, reason="no one to share with"))
                return character_id, user_id, outbound, None
            target_id = lid
            target_name = lname
        if target_id is None and isinstance(target_name, str) and target_name.strip():
            if not want_last:
                tid, nerr = manager.resolve_live_name(target_name)
                if nerr == "name ambiguous":
                    outbound.append(msg(ServerMessageType.ERROR, reason="name ambiguous"))
                    return character_id, user_id, outbound, None
                target_id = tid
        if target_id is None:
            if not (
                isinstance(target_name, str) and target_name.strip()
            ) and raw_pid is None and not want_last:
                outbound.append(msg(ServerMessageType.ERROR, reason="share target required"))
            else:
                outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        if target_id == character_id:
            outbound.append(msg(ServerMessageType.ERROR, reason="cannot share with yourself"))
            return character_id, user_id, outbound, None
        if target_id not in manager.online_ids():
            outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        if manager.is_ignored_by(target_id, character_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="player unavailable"))
            return character_id, user_id, outbound, None
        if manager.is_ignored_by(character_id, target_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="you ignore that player"))
            return character_id, user_id, outbound, None
        meta_pre = manager.get_meta(character_id)
        from network.websocket_manager import _is_idle as _idle_chk

        was_idle = _idle_chk(meta_pre) if meta_pre else False
        was_afk, afk_msg_snap = _afk_snap(meta_pre)
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
        tmeta = manager.get_meta(target_id)
        name = (meta or {}).get("name") or "Hero"
        tname = (tmeta or {}).get("name") or (
            target_name.strip() if isinstance(target_name, str) else "Hero"
        )
        you_zone = None
        you_x = you_y = None
        if meta is not None:
            try:
                you_x, you_y = int(meta["x"]), int(meta["y"])
                you_zone = zone_at(you_x, you_y)
            except Exception:
                you_zone = None
        zone_bit = (
            f"the {you_zone}"
            if you_zone in ("town", "field", "dungeon")
            else "the map"
        )
        pos_bit = (
            f" at ({you_x}, {you_y})"
            if you_x is not None and you_y is not None
            else ""
        )
        share_line = f"{name} shares their location: {zone_bit}{pos_bit}."
        share_msg: dict = {
            "type": "share",
            "from": name,
            "from_id": character_id,
            "to": tname,
            "to_id": target_id,
            "zone": you_zone,
            "x": you_x,
            "y": you_y,
            "message": share_line,
        }
        sid_s = manager.session_id(character_id)
        if sid_s is not None:
            share_msg["session_id"] = sid_s
        delivered = await manager.send(target_id, share_msg)
        if not delivered:
            manager.refund_chat(
                character_id, restore_afk=was_afk, afk_message=afk_msg_snap
            )
            outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        manager.note_whisper_from(character_id, target_id, tname)
        manager.note_whisper_from(target_id, character_id, name)
        echo = dict(share_msg)
        echo["message"] = f"Location shared with {tname}."
        target_afk = bool((tmeta or {}).get("afk"))
        if target_afk:
            echo["target_afk"] = True
            am = (tmeta or {}).get("afk_message")
            if isinstance(am, str) and am.strip():
                echo["target_afk_message"] = am.strip()[:48]
        outbound.append(echo)
        if was_idle:
            await manager.publish_status(character_id)
        return character_id, user_id, outbound, None

    # --- Poke / nudge (private multiplayer attention, not a party) ---
    if msg_type in ("poke", "nudge", "hey", "attention", "tap"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        target_name = data.get("to") or data.get("name") or data.get("target") or data.get("player")
        want_last = bool(data.get("reply")) or (
            isinstance(target_name, str)
            and target_name.strip().lower() in ("@last", "last", "!")
        )
        raw_pid = None
        if data.get("to_id") is not None:
            raw_pid = data.get("to_id")
        elif data.get("player_id") is not None:
            raw_pid = data.get("player_id")
        target_id = (
            manager.find_id_by_player_id(raw_pid) if raw_pid is not None else None
        )
        if raw_pid is not None and target_id is None:
            from network.websocket_manager import coerce_character_id

            if coerce_character_id(raw_pid) is None:
                outbound.append(msg(ServerMessageType.ERROR, reason="player not found"))
            else:
                outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        if want_last and target_id is None:
            lid, lname = manager.last_whisper_from(character_id)
            if lid is None:
                lid, lname = manager.last_emote_to(character_id)
            if lid is None:
                lid, lname = manager.last_invite_from(character_id)
            if lid is None:
                lid, lname = manager.last_invite_to(character_id)
            if lid is None:
                outbound.append(msg(ServerMessageType.ERROR, reason="no one to poke"))
                return character_id, user_id, outbound, None
            target_id = lid
            target_name = lname
        if target_id is None and isinstance(target_name, str) and target_name.strip():
            if not want_last:
                tid, nerr = manager.resolve_live_name(target_name)
                if nerr == "name ambiguous":
                    outbound.append(msg(ServerMessageType.ERROR, reason="name ambiguous"))
                    return character_id, user_id, outbound, None
                target_id = tid
        if target_id is None:
            if not (
                isinstance(target_name, str) and target_name.strip()
            ) and raw_pid is None and not want_last:
                outbound.append(msg(ServerMessageType.ERROR, reason="poke target required"))
            else:
                outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        if target_id == character_id:
            outbound.append(msg(ServerMessageType.ERROR, reason="cannot poke yourself"))
            return character_id, user_id, outbound, None
        if target_id not in manager.online_ids():
            outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        if manager.is_ignored_by(target_id, character_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="player unavailable"))
            return character_id, user_id, outbound, None
        if manager.is_ignored_by(character_id, target_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="you ignore that player"))
            return character_id, user_id, outbound, None
        meta_pre = manager.get_meta(character_id)
        from network.websocket_manager import _is_idle as _idle_chk

        was_idle = _idle_chk(meta_pre) if meta_pre else False
        was_afk, afk_msg_snap = _afk_snap(meta_pre)
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
        tmeta = manager.get_meta(target_id)
        name = (meta or {}).get("name") or "Hero"
        tname = (tmeta or {}).get("name") or (
            target_name.strip() if isinstance(target_name, str) else "Hero"
        )
        poke_line = f"{name} is trying to get your attention."
        poke_msg: dict = {
            "type": "poke",
            "from": name,
            "from_id": character_id,
            "to": tname,
            "to_id": target_id,
            "message": poke_line,
        }
        sid_p = manager.session_id(character_id)
        if sid_p is not None:
            poke_msg["session_id"] = sid_p
        delivered = await manager.send(target_id, poke_msg)
        if not delivered:
            manager.refund_chat(
                character_id, restore_afk=was_afk, afk_message=afk_msg_snap
            )
            outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        manager.note_whisper_from(character_id, target_id, tname)
        manager.note_whisper_from(target_id, character_id, name)
        echo = dict(poke_msg)
        echo["message"] = f"You poked {tname}."
        target_afk = bool((tmeta or {}).get("afk"))
        if target_afk:
            echo["target_afk"] = True
            am = (tmeta or {}).get("afk_message")
            if isinstance(am, str) and am.strip():
                echo["target_afk_message"] = am.strip()[:48]
        outbound.append(echo)
        if was_idle:
            await manager.publish_status(character_id)
        return character_id, user_id, outbound, None

    # --- Ask where (private location request — they may /share @last) ---
    if msg_type in (
        "askwhere",
        "ask_where",
        "askpos",
        "ask_pos",
        "locate",
        "whereru",
        "where_r_u",
        "whereyou",
    ):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        target_name = data.get("to") or data.get("name") or data.get("target") or data.get("player")
        want_last = bool(data.get("reply")) or (
            isinstance(target_name, str)
            and target_name.strip().lower() in ("@last", "last", "!")
        )
        raw_pid = None
        if data.get("to_id") is not None:
            raw_pid = data.get("to_id")
        elif data.get("player_id") is not None:
            raw_pid = data.get("player_id")
        target_id = (
            manager.find_id_by_player_id(raw_pid) if raw_pid is not None else None
        )
        if raw_pid is not None and target_id is None:
            from network.websocket_manager import coerce_character_id

            if coerce_character_id(raw_pid) is None:
                outbound.append(msg(ServerMessageType.ERROR, reason="player not found"))
            else:
                outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        if want_last and target_id is None:
            lid, lname = manager.last_whisper_from(character_id)
            if lid is None:
                lid, lname = manager.last_emote_to(character_id)
            if lid is None:
                lid, lname = manager.last_invite_from(character_id)
            if lid is None:
                lid, lname = manager.last_invite_to(character_id)
            if lid is None:
                outbound.append(msg(ServerMessageType.ERROR, reason="no one to ask"))
                return character_id, user_id, outbound, None
            target_id = lid
            target_name = lname
        if target_id is None and isinstance(target_name, str) and target_name.strip():
            if not want_last:
                tid, nerr = manager.resolve_live_name(target_name)
                if nerr == "name ambiguous":
                    outbound.append(msg(ServerMessageType.ERROR, reason="name ambiguous"))
                    return character_id, user_id, outbound, None
                target_id = tid
        if target_id is None:
            if not (
                isinstance(target_name, str) and target_name.strip()
            ) and raw_pid is None and not want_last:
                outbound.append(msg(ServerMessageType.ERROR, reason="askwhere target required"))
            else:
                outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        if target_id == character_id:
            outbound.append(msg(ServerMessageType.ERROR, reason="cannot ask yourself"))
            return character_id, user_id, outbound, None
        if target_id not in manager.online_ids():
            outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        if manager.is_ignored_by(target_id, character_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="player unavailable"))
            return character_id, user_id, outbound, None
        if manager.is_ignored_by(character_id, target_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="you ignore that player"))
            return character_id, user_id, outbound, None
        meta_pre = manager.get_meta(character_id)
        from network.websocket_manager import _is_idle as _idle_chk

        was_idle = _idle_chk(meta_pre) if meta_pre else False
        was_afk, afk_msg_snap = _afk_snap(meta_pre)
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
        tmeta = manager.get_meta(target_id)
        name = (meta or {}).get("name") or "Hero"
        tname = (tmeta or {}).get("name") or (
            target_name.strip() if isinstance(target_name, str) else "Hero"
        )
        req_line = f"{name} asks where you are. /share @last to reply."
        req_msg: dict = {
            "type": "askwhere",
            "from": name,
            "from_id": character_id,
            "to": tname,
            "to_id": target_id,
            "message": req_line,
        }
        sid_a = manager.session_id(character_id)
        if sid_a is not None:
            req_msg["session_id"] = sid_a
        delivered = await manager.send(target_id, req_msg)
        if not delivered:
            manager.refund_chat(
                character_id, restore_afk=was_afk, afk_message=afk_msg_snap
            )
            outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        manager.note_whisper_from(character_id, target_id, tname)
        manager.note_whisper_from(target_id, character_id, name)
        echo = dict(req_msg)
        echo["message"] = f"You asked {tname} where they are."
        target_afk = bool((tmeta or {}).get("afk"))
        if target_afk:
            echo["target_afk"] = True
            am = (tmeta or {}).get("afk_message")
            if isinstance(am, str) and am.strip():
                echo["target_afk_message"] = am.strip()[:48]
        outbound.append(echo)
        if was_idle:
            await manager.publish_status(character_id)
        return character_id, user_id, outbound, None

    # --- Last meetup inviter (who invited you) ---
    if msg_type in ("lastinvite", "last_invite", "who_invite", "invite_last"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        lid, lname = manager.last_invite_from(character_id)
        peer = None
        online = False
        peer_afk = False
        if lid is not None:
            online = manager.is_online(lid)
            pmeta = manager.get_meta(lid) if online else None
            peer_afk = bool(pmeta.get("afk")) if pmeta else False
            peer = {
                "id": lid,
                "name": lname or (pmeta or {}).get("name"),
                "online": online,
                "afk": peer_afk,
            }
            psid = (pmeta or {}).get("session_id") if pmeta else None
            if psid is not None:
                peer["session_id"] = psid
            if peer_afk and pmeta is not None:
                pam = pmeta.get("afk_message")
                if isinstance(pam, str) and pam.strip():
                    peer["afk_message"] = pam.strip()[:48]
        outbound.append(
            msg(
                "lastinvite",
                peer=peer,
                online=online,
                message=(
                    f"Last invite from: {peer['name']}"
                    + (" (online)" if online else " (offline)" if peer else "")
                    if peer
                    else "No meetup invite yet."
                ),
            )
        )
        return character_id, user_id, outbound, None

    # --- Accept / decline last meetup invite (not a party — private reply only) ---
    if msg_type in (
        "accept",
        "coming",
        "invite_accept",
        "decline",
        "later",
        "invite_decline",
        "pass_invite",
    ):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        accepting = msg_type in ("accept", "coming", "invite_accept")
        lid, lname = manager.last_invite_from(character_id)
        if lid is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="no invite to answer"))
            return character_id, user_id, outbound, None
        if lid not in manager.online_ids():
            outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        if manager.is_ignored_by(lid, character_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="player unavailable"))
            return character_id, user_id, outbound, None
        if manager.is_ignored_by(character_id, lid):
            outbound.append(msg(ServerMessageType.ERROR, reason="you ignore that player"))
            return character_id, user_id, outbound, None
        meta_pre = manager.get_meta(character_id)
        from network.websocket_manager import _is_idle as _idle_chk

        was_idle = _idle_chk(meta_pre) if meta_pre else False
        was_afk, afk_msg_snap = _afk_snap(meta_pre)
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
        tmeta = manager.get_meta(lid)
        name = (meta or {}).get("name") or "Hero"
        tname = (tmeta or {}).get("name") or lname or "Hero"
        if accepting:
            line = f"{name} is coming to meet you."
            self_line = f"You told {tname} you are coming."
            action = "accept"
        else:
            line = f"{name} cannot meet right now."
            self_line = f"You declined {tname}'s invite."
            action = "decline"
        reply_msg: dict = {
            "type": "invite_reply",
            "action": action,
            "from": name,
            "from_id": character_id,
            "to": tname,
            "to_id": lid,
            "message": line,
        }
        sid_r = manager.session_id(character_id)
        if sid_r is not None:
            reply_msg["session_id"] = sid_r
        delivered = await manager.send(lid, reply_msg)
        if not delivered:
            manager.refund_chat(
                character_id, restore_afk=was_afk, afk_message=afk_msg_snap
            )
            outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        # Consume invite so double-accept cannot spam the inviter
        manager.clear_last_invite(character_id)
        # Inviter's outgoing pointer no longer pending
        inv_to, _ = manager.last_invite_to(lid)
        if inv_to == character_id:
            manager.clear_last_invite_to(lid)
        # Accept also sets /r peer for easy follow-up whisper
        if accepting:
            manager.note_whisper_from(character_id, lid, tname)
            manager.note_whisper_from(lid, character_id, name)
        echo = dict(reply_msg)
        echo["message"] = self_line
        outbound.append(echo)
        if was_idle:
            await manager.publish_status(character_id)
        return character_id, user_id, outbound, None

    # --- Nearby combat roster (multiplayer awareness) ---
    if msg_type in ("fighting", "combats", "battles", "in_combat", "combat_near"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        fighters = manager.nearby_combat_roster(character_id)
        n = len(fighters)
        names = [str(p.get("name") or "?") for p in fighters[:8]]
        name_bit = (", ".join(names) + (f" +{n - 8}" if n > 8 else "")) if names else "none"
        outbound.append(
            msg(
                "fighting",
                players=fighters,
                nearby_combat=n,
                nearby_count=len(manager.ids_nearby(character_id)),
                online=len(manager.online_ids()),
                afk_count=manager.afk_count(),
                combat_count=manager.combat_count(),
                message=f"{n} nearby fighting · {name_bit}",
            )
        )
        return character_id, user_id, outbound, None

    # --- Graceful quit / logout (client should close socket after ack) ---
    if msg_type in ("quit", "logout", "exit", "leave_world"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        outbound.append(
            msg(
                "quit",
                ok=True,
                message="Farewell, hero.",
                reason="quit",
            )
        )
        # Soft disconnect after outbound is delivered by main loop
        try:
            await manager.disconnect(character_id, reason="quit")
        except Exception:
            pass
        return None, user_id, outbound, None

    # --- Stuck / unstuck / home: free return to town spawn (multiplayer safety) ---
    if msg_type in ("stuck", "unstuck", "home", "recall_home"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        if combat_engine.is_in_combat(character_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="in combat"))
            return character_id, user_id, outbound, None
        meta = manager.get_meta(character_id)
        if not meta:
            outbound.append(msg(ServerMessageType.ERROR, reason="not online"))
            return character_id, user_id, outbound, None
        try:
            cx, cy = int(meta["x"]), int(meta["y"])
        except Exception:
            cx, cy = SPAWN_X, SPAWN_Y
        already = cx == SPAWN_X and cy == SPAWN_Y and zone_at(cx, cy) == "town"
        # Already home: no rate burn, no teleport — still activity (clear AFK badge)
        if already:
            was_afk_home = manager.mark_active(character_id)
            if was_afk_home:
                await manager.publish_status(character_id, pulse_online=True)
            outbound.append(
                msg(
                    "stuck",
                    ok=True,
                    x=SPAWN_X,
                    y=SPAWN_Y,
                    zone="town",
                    teleported=False,
                    session_id=manager.session_id(character_id),
                    message="You are already in town.",
                    afk=False,
                )
            )
            return character_id, user_id, outbound, None
        # Soft rate limit so stuck cannot be spammed as free teleport
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
        # allow_chat cleared AFK; keep stamps clean (including optional reason)
        meta["afk"] = False
        meta["afk_since"] = None
        meta["afk_message"] = None
        name = (meta.get("name") or "Hero")
        char = await apply_character_patch(
            character_id, {"world_x": SPAWN_X, "world_y": SPAWN_Y}
        )
        aoi = await manager.publish_move(character_id, SPAWN_X, SPAWN_Y, seq=None)
        outbound.extend(aoi)
        outbound.append(
            msg(
                ServerMessageType.MOVE_OK,
                ok=True,
                x=SPAWN_X,
                y=SPAWN_Y,
                seq=None,
                reason="stuck",
                zone="town",
            )
        )
        # Nearby system notice — multiplayer awareness of free home recall
        notice = msg(
            ServerMessageType.CHAT,
            player_id=character_id,
            name="System",
            text=f"{name} returned to town.",
            channel="system",
            system=True,
        )
        sid_s = manager.session_id(character_id)
        if sid_s is not None:
            notice["session_id"] = sid_s
        await manager.broadcast_nearby(
            character_id, notice, include_self=False, respect_ignore=False
        )
        await manager.publish_status(character_id, pulse_online=True)
        outbound.append(
            msg(
                "stuck",
                ok=True,
                x=SPAWN_X,
                y=SPAWN_Y,
                zone="town",
                teleported=True,
                session_id=manager.session_id(character_id),
                character=char,
                message="You find your way back to town.",
            )
        )
        return character_id, user_id, outbound, None

    # --- Server version / about (multiplayer ops + client HUD) ---
    if msg_type in ("version", "ver", "about", "server", "info"):
        from config import PROCESS_STARTED_AT, VERSION as _VER
        import time as _time

        if character_id is not None:
            manager.touch(character_id)
        outbound.append(
            msg(
                "version",
                version=_VER,
                online=len(manager.online_ids()),
                afk_count=manager.afk_count(),
                zones=manager.zone_counts(),
                uptime=max(0, int(_time.time() - PROCESS_STARTED_AT)),
                service="dq1-mmo",
            )
        )
        return character_id, user_id, outbound, None

    # --- Session play time this connection (multiplayer self snapshot) ---
    if msg_type in ("played", "session", "session_time", "online_time"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        meta = manager.get_meta(character_id)
        if not meta:
            outbound.append(msg(ServerMessageType.ERROR, reason="not online"))
            return character_id, user_id, outbound, None
        import time as _time
        from network.websocket_manager import _is_idle as _idle_played

        started = float(meta.get("session_started") or 0.0)
        now = _time.monotonic()
        age = max(0, int(now - started)) if started else 0
        h, rem = divmod(age, 3600)
        m, s = divmod(rem, 60)
        if h:
            pretty = f"{h}h {m}m {s}s"
        elif m:
            pretty = f"{m}m {s}s"
        else:
            pretty = f"{s}s"
        you_zone = None
        try:
            you_zone = zone_at(int(meta["x"]), int(meta["y"]))
        except Exception:
            you_zone = None
        sid = manager.session_id(character_id)
        you_afk = bool(meta.get("afk"))
        body = {
            "type": "played",
            "seconds": age,
            "session_id": sid,
            "name": meta.get("name"),
            "zone": you_zone,
            "online": len(manager.online_ids()),
            "afk_count": manager.afk_count(),
            "nearby_count": len(manager.ids_nearby(character_id)),
            "nearby_afk": manager.nearby_afk_count(character_id),
            "afk": you_afk,
            "idle": _idle_played(meta),
            "message": f"This session: {pretty}.",
        }
        if you_afk:
            am = meta.get("afk_message")
            if isinstance(am, str) and am.strip():
                body["afk_message"] = am.strip()[:48]
        outbound.append(body)
        return character_id, user_id, outbound, None

    # --- Server time / uptime ---
    if msg_type in ("time", "uptime", "servertime", "clock"):
        from config import PROCESS_STARTED_AT, VERSION as _VER
        import time as _time

        if character_id is not None:
            manager.touch(character_id)
        now = _time.time()
        up = max(0, int(now - PROCESS_STARTED_AT))
        outbound.append(
            msg(
                "time",
                server_t=now,
                uptime=up,
                uptime_hms=_format_uptime(up),
                version=_VER,
                online=len(manager.online_ids()),
            )
        )
        return character_id, user_id, outbound, None

    # --- Ignore / mute list (session soft-grace) ---
    if msg_type in (ClientMessageType.IGNORE, "ignore", "mute", "block"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        target_name = data.get("name") or data.get("to") or data.get("player")
        target_id = manager.find_id_by_player_id(
            data.get("player_id") or data.get("id") or data.get("to_id")
        )
        if target_id is None and isinstance(target_name, str):
            target_id, nerr = manager.resolve_live_name(target_name)
            if nerr == "name ambiguous":
                outbound.append(msg(ServerMessageType.ERROR, reason="name ambiguous"))
                return character_id, user_id, outbound, None
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

    if msg_type in (ClientMessageType.UNIGNORE, "unignore", "unmute", "unblock"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        target_name = data.get("name") or data.get("to") or data.get("player")
        target_id = manager.find_id_by_player_id(
            data.get("player_id") or data.get("id") or data.get("to_id")
        )
        if target_id is None and isinstance(target_name, str):
            # Prefer live resolve; fall back to offline ignore_names scan
            target_id, nerr = manager.resolve_live_name(target_name)
            if nerr == "name ambiguous":
                outbound.append(msg(ServerMessageType.ERROR, reason="name ambiguous"))
                return character_id, user_id, outbound, None
            if target_id is None:
                # Offline ignored player: match cached name
                meta = manager.get_meta(character_id) or {}
                names = meta.get("ignore_names") or {}
                key = target_name.strip().lower()
                for tid, n in names.items():
                    if str(n).strip().lower() == key:
                        try:
                            target_id = int(tid)
                        except (TypeError, ValueError):
                            target_id = None
                        break
        if target_id is None:
            # allow unignore by id even if offline (strict id parse — no bool→1)
            from network.websocket_manager import coerce_character_id

            target_id = coerce_character_id(
                data.get("player_id")
                if data.get("player_id") is not None
                else data.get("id")
            )
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

    if msg_type in (
        ClientMessageType.IGNORES,
        "ignores",
        "ignore_list",
        "blocklist",
        "blocks",
    ):
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
        afk_f = data.get("afk")
        idle_f = data.get("idle")
        q_clean = q.strip() if isinstance(q, str) else ""

        def _parse_yn_token(raw: Any) -> bool | None | str:
            """Return True/False, None if unset, or 'bad' if invalid string."""
            if raw is None or raw == "":
                return None
            if isinstance(raw, bool):
                return raw
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                return bool(int(raw))
            if isinstance(raw, str) and raw.strip():
                s = raw.strip().lower()
                if s in ("yes", "1", "true", "afk", "away", "idle"):
                    return True
                if s in ("no", "0", "false", "back", "active"):
                    return False
                return "bad"
            return "bad"

        combat_f = data.get("combat")
        if combat_f is None:
            combat_f = data.get("fighting")
        # Pull zone:/in:, afk:, idle:, combat: tokens from free text (order-independent)
        if isinstance(q_clean, str) and q_clean:
            m_zone = re.search(r"(?:^|\s)(?:zone|in):(\w+)\b", q_clean, flags=re.I)
            if m_zone:
                zone_f = m_zone.group(1)
                q_clean = (q_clean[: m_zone.start()] + q_clean[m_zone.end() :]).strip()
            m_afk = re.search(r"(?:^|\s)afk:(\w+)\b", q_clean, flags=re.I)
            if m_afk:
                tok = m_afk.group(1).lower()
                if tok not in ("yes", "no", "1", "0", "true", "false"):
                    outbound.append(
                        msg(ServerMessageType.ERROR, reason="invalid afk filter")
                    )
                    return character_id, user_id, outbound, None
                afk_f = tok in ("yes", "1", "true")
                q_clean = (q_clean[: m_afk.start()] + q_clean[m_afk.end() :]).strip()
            m_idle = re.search(r"(?:^|\s)idle:(\w+)\b", q_clean, flags=re.I)
            if m_idle:
                tok = m_idle.group(1).lower()
                if tok not in ("yes", "no", "1", "0", "true", "false"):
                    outbound.append(
                        msg(ServerMessageType.ERROR, reason="invalid idle filter")
                    )
                    return character_id, user_id, outbound, None
                idle_f = tok in ("yes", "1", "true")
                q_clean = (q_clean[: m_idle.start()] + q_clean[m_idle.end() :]).strip()
            m_combat = re.search(
                r"(?:^|\s)(?:combat|fighting):(\w+)\b", q_clean, flags=re.I
            )
            if m_combat:
                tok = m_combat.group(1).lower()
                if tok not in ("yes", "no", "1", "0", "true", "false"):
                    outbound.append(
                        msg(ServerMessageType.ERROR, reason="invalid combat filter")
                    )
                    return character_id, user_id, outbound, None
                combat_f = tok in ("yes", "1", "true")
                q_clean = (
                    q_clean[: m_combat.start()] + q_clean[m_combat.end() :]
                ).strip()
            # Bare "afk" / "away" as whole residual query
            if q_clean.lower() in ("afk", "away"):
                afk_f = True
                q_clean = ""
            if q_clean.lower() in ("idle",):
                idle_f = True
                q_clean = ""
            if q_clean.lower() in ("combat", "fighting", "battles"):
                combat_f = True
                q_clean = ""
        # Validate zone first so "zone:moon" → invalid zone (not "find query required")
        if isinstance(zone_f, str) and zone_f.strip():
            znorm = zone_f.strip().lower()
            if znorm not in ("town", "field", "dungeon"):
                outbound.append(msg(ServerMessageType.ERROR, reason="invalid zone"))
                return character_id, user_id, outbound, None
            zone_f = znorm
        else:
            zone_f = None
        afk_filter = _parse_yn_token(afk_f)
        if afk_filter == "bad":
            outbound.append(msg(ServerMessageType.ERROR, reason="invalid afk filter"))
            return character_id, user_id, outbound, None
        idle_filter = _parse_yn_token(idle_f)
        if idle_filter == "bad":
            outbound.append(msg(ServerMessageType.ERROR, reason="invalid idle filter"))
            return character_id, user_id, outbound, None
        combat_filter = _parse_yn_token(combat_f)
        if combat_filter == "bad":
            outbound.append(msg(ServerMessageType.ERROR, reason="invalid combat filter"))
            return character_id, user_id, outbound, None
        # Bare zone and/or afk/idle/combat with empty name is OK
        if (
            not q_clean
            and zone_f is None
            and afk_filter is None
            and idle_filter is None
            and combat_filter is None
        ):
            outbound.append(msg(ServerMessageType.ERROR, reason="find query required"))
            return character_id, user_id, outbound, None
        limit = data.get("limit") or 20
        try:
            limit_i = int(limit)
        except (TypeError, ValueError):
            limit_i = 20
        hits = manager.find_by_prefix(
            q_clean,
            limit=limit_i,
            zone=zone_f,
            afk=afk_filter,
            idle=idle_filter,
            combat=combat_filter,
        )
        bits: list[str] = []
        if q_clean:
            bits.append(q_clean[:24])
        if zone_f:
            bits.append(f"zone:{zone_f}")
        if afk_filter is True:
            bits.append("afk:yes")
        elif afk_filter is False:
            bits.append("afk:no")
        if idle_filter is True:
            bits.append("idle:yes")
        elif idle_filter is False:
            bits.append("idle:no")
        if combat_filter is True:
            bits.append("combat:yes")
        elif combat_filter is False:
            bits.append("combat:no")
        outbound.append(
            msg(
                ServerMessageType.FIND,
                query=" ".join(bits),
                zone=zone_f,
                afk=afk_filter,
                idle=idle_filter,
                combat=combat_filter,
                players=hits,
                online=len(manager.online_ids()),
                afk_count=manager.afk_count(),
                combat_count=manager.combat_count(),
                count=len(hits),
                zones=manager.zone_counts(),
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
        "cast",
        "cast_spell",
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
    # Shortcuts: {type:cast,spell:heal} or {type:heal}/{type:repel}/… when not in combat
    _FIELD_SHORTCUTS = {
        "heal",
        "healmore",
        "return",
        "repel",
        "outside",
        "radiant",
    }
    if (
        msg_type in (ClientMessageType.USE_SPELL, "use_spell", "cast", "cast_spell")
        or (msg_type in _FIELD_SHORTCUTS and not combat_engine.is_in_combat(character_id))
    ) and not combat_engine.is_in_combat(character_id):
        if msg_type in _FIELD_SHORTCUTS:
            spell_id = str(msg_type)
        else:
            spell_id = str(
                data.get("spell")
                or data.get("id")
                or data.get("name")
                or ""
            ).strip().lower().replace(" ", "")
        # normalize aliases
        _spell_alias = {
            "healmore": "healmore",
            "heal_more": "healmore",
            "return": "return",
            "warp": "return",
            "town": "return",
            "repel": "repel",
            "holy_protection": "repel",
            "outside": "outside",
            "exit": "outside",
            "radiant": "radiant",
            "light": "radiant",
            "heal": "heal",
        }
        spell_id = _spell_alias.get(spell_id, spell_id)
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
        # Casting is multiplayer activity — clear AFK for peers
        was_afk_cast = manager.mark_active(character_id)
        if was_afk_cast:
            await manager.publish_status(character_id, pulse_online=True)
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
        "cast",
        "cast_spell",
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
            # Multiplayer: nearby system note for victory / flee / defeat
            await _announce_combat_outcome(character_id, str(battle.outcome))
            if battle.outcome == "defeat":
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

        # Capture AFK before allow_move clears it so peers get an idle-clear update
        was_afk = bool(meta.get("afk"))
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
        # Multiplayer: walking clears manual AFK — notify AOI + roster
        if was_afk:
            await manager.publish_status(character_id, pulse_online=True)

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
                # Multiplayer: nearby notice that a hero engaged (not global spam)
                hero_nm = (manager.get_meta(character_id) or {}).get("name") or "Hero"
                await manager.broadcast_nearby(
                    character_id,
                    msg(
                        ServerMessageType.CHAT,
                        player_id=character_id,
                        name="System",
                        text=f"{hero_nm} is fighting!",
                        channel="system",
                        system=True,
                    ),
                    include_self=False,
                    respect_ignore=False,
                )
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
                tid, name_err = manager.resolve_live_name(target_name)
                if name_err == "name ambiguous":
                    outbound.append(msg(ServerMessageType.ERROR, reason="name ambiguous"))
                    return character_id, user_id, outbound, None
                target_id = tid
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
        meta_pre = manager.get_meta(character_id)
        was_idle = False
        if meta_pre is not None:
            from network.websocket_manager import _is_idle as _idle_chk

            was_idle = _idle_chk(meta_pre)
        was_afk, afk_msg_snap = _afk_snap(meta_pre)
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
        sid = manager.session_id(character_id)
        if sid is not None:
            whisper_msg["session_id"] = sid
        target_afk = bool((tmeta or {}).get("afk"))
        target_afk_msg = None
        if target_afk and tmeta is not None:
            am = tmeta.get("afk_message")
            if isinstance(am, str) and am.strip():
                target_afk_msg = am.strip()[:48]
        # Deliver to target; fail closed if socket is dead (don't echo a lie)
        delivered = await manager.send(target_id, whisper_msg)
        if not delivered:
            # Don't punish sender for multiplayer delivery races
            manager.refund_chat(
                character_id, restore_afk=was_afk, afk_message=afk_msg_snap
            )
            outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        # Sender echo may note AFK so UI can show "they may not reply"
        echo = dict(whisper_msg)
        if target_afk:
            echo["target_afk"] = True
            if target_afk_msg:
                echo["target_afk_message"] = target_afk_msg
        outbound.append(echo)
        # Target remembers us for their /r; we remember them if they reply later
        manager.note_whisper_from(target_id, character_id, name)
        manager.note_whisper_from(character_id, target_id, tname)
        if was_idle:
            await manager.publish_status(character_id)
        return character_id, user_id, outbound, None

    # --- Chat: global / nearby AOI / zone (`say`/`s` nearby; `chat`/`g` global; yell/shout zone) ---
    if msg_type in (
        ClientMessageType.CHAT,
        ClientMessageType.SAY,
        "chat",
        "say",
        "s",
        "g",
        "nearby_chat",
        "yell",
        "shout",
    ):
        text = sanitize_chat(data.get("text") or data.get("message") or data.get("msg"))
        if text is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="empty chat"))
            return character_id, user_id, outbound, None
        meta = manager.get_meta(character_id)
        name = (meta or {}).get("name") or "Hero"
        # Explicit channel wins; say/s/nearby_chat → nearby; g → global; yell/shout → zone
        channel = (data.get("channel") or "").lower().strip()
        # Reserved for server-originated traffic only (level-up fanfare, etc.)
        # Check before rate-limit so clients get a clear reason, not chat_rate_limit.
        if channel in ("system", "admin", "server", "gm"):
            outbound.append(
                msg(ServerMessageType.ERROR, reason="reserved channel")
            )
            return character_id, user_id, outbound, None
        if channel not in ("global", "nearby", "local", "whisper", "zone", "area", "shout", "yell"):
            if msg_type in (ClientMessageType.SAY, "say", "s", "nearby_chat"):
                channel = "nearby"
            elif msg_type == "g":
                channel = "global"
            elif msg_type in ("yell", "shout"):
                channel = "zone"
            else:
                channel = "global"
        if channel == "local":
            channel = "nearby"
        if channel == "area":
            channel = "zone"
        # Shout/yell = same-zone broadcast (multiplayer area shout, not global spam)
        if channel in ("shout", "yell"):
            channel = "zone"
        # chat with channel=whisper and `to` name/id → private path
        # Validate target BEFORE burning chat rate (same as dedicated whisper handler)
        if channel == "whisper":
            target_name = data.get("to") or data.get("name") or data.get("target")
            target_id = manager.find_id_by_player_id(
                data.get("to_id") or data.get("player_id") or data.get("id")
            )
            if target_id is None and isinstance(target_name, str) and target_name.strip():
                tid, nerr = manager.resolve_live_name(target_name)
                if nerr == "name ambiguous":
                    outbound.append(msg(ServerMessageType.ERROR, reason="name ambiguous"))
                    return character_id, user_id, outbound, None
                target_id = tid
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
            from network.websocket_manager import _is_idle as _idle_chk

            was_idle_w = _idle_chk(meta) if meta else False
            was_afk_w, afk_msg_w = _afk_snap(meta)
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
            sid_w = manager.session_id(character_id)
            if sid_w is not None:
                whisper_msg["session_id"] = sid_w
            target_afk_w = bool((tmeta or {}).get("afk"))
            target_afk_msg_w = None
            if target_afk_w and tmeta is not None:
                amw = tmeta.get("afk_message")
                if isinstance(amw, str) and amw.strip():
                    target_afk_msg_w = amw.strip()[:48]
            delivered = await manager.send(target_id, whisper_msg)
            if not delivered:
                manager.refund_chat(
                    character_id, restore_afk=was_afk_w, afk_message=afk_msg_w
                )
                outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
                return character_id, user_id, outbound, None
            echo_w = dict(whisper_msg)
            if target_afk_w:
                echo_w["target_afk"] = True
                if target_afk_msg_w:
                    echo_w["target_afk_message"] = target_afk_msg_w
            outbound.append(echo_w)
            manager.note_whisper_from(target_id, character_id, name)
            manager.note_whisper_from(character_id, target_id, tname)
            if was_idle_w:
                await manager.publish_status(character_id)
            return character_id, user_id, outbound, None
        from network.websocket_manager import _is_idle as _idle_chk

        was_idle = _idle_chk(meta) if meta else False
        zone_name = None
        if meta is not None:
            try:
                zone_name = zone_at(int(meta["x"]), int(meta["y"]))
            except Exception:
                zone_name = None
        # Zone chat only from walkable social zones (not water/wall)
        if channel == "zone" and zone_name not in ("town", "field", "dungeon"):
            outbound.append(msg(ServerMessageType.ERROR, reason="not in a zone"))
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
        chat_msg = msg(
            ServerMessageType.CHAT,
            player_id=character_id,
            name=name,
            text=text,
            channel=channel,
            zone=zone_name if channel == "zone" else None,
        )
        sid_c = manager.session_id(character_id)
        if sid_c is not None:
            chat_msg["session_id"] = sid_c
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
        if was_idle:
            await manager.publish_status(character_id)
        return character_id, user_id, outbound, None

    # --- Social roll (nearby 1d100 — multiplayer icebreaker) ---
    if msg_type in ("roll", "dice", "d100"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        # Validate sides BEFORE allow_chat so bad rolls never burn rate or clear AFK.
        # Optional sides: {type:roll, sides:20} default 100, must be 2..1000.
        # Do NOT use `or` for default — sides=0 is falsy and used to become 100.
        if "sides" in data:
            raw_sides = data.get("sides")
        elif "d" in data:
            raw_sides = data.get("d")
        else:
            raw_sides = 100
        try:
            # bool is a subclass of int — reject True/False as dice sizes
            if isinstance(raw_sides, bool):
                raise ValueError("bool sides")
            # Non-integer floats must not silently become d2 via int(2.7)
            if isinstance(raw_sides, float):
                import math as _math

                if not _math.isfinite(raw_sides) or not raw_sides.is_integer():
                    raise ValueError("float sides")
                sides_i = int(raw_sides)
            elif isinstance(raw_sides, int):
                sides_i = raw_sides
            elif isinstance(raw_sides, str):
                s = raw_sides.strip()
                if not s or not s.lstrip("-").isdigit():
                    raise ValueError("str sides")
                sides_i = int(s)
            else:
                sides_i = int(raw_sides)
        except (TypeError, ValueError):
            outbound.append(msg(ServerMessageType.ERROR, reason="invalid roll sides"))
            return character_id, user_id, outbound, None
        if sides_i < 2 or sides_i > 1000:
            outbound.append(
                msg(
                    ServerMessageType.ERROR,
                    reason="invalid roll sides",
                    sides=sides_i,
                    min=2,
                    max=1000,
                )
            )
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
        name = (meta or {}).get("name") or "Hero"
        import random as _random

        value = _random.randint(1, sides_i)
        roll_text = f"{name} rolls d{sides_i}: {value}"
        roll_msg = msg(
            ServerMessageType.CHAT,
            player_id=character_id,
            name="System",
            text=roll_text,
            channel="system",
            system=True,
            roll={"sides": sides_i, "value": value, "name": name},
        )
        sid_r = manager.session_id(character_id)
        if sid_r is not None:
            roll_msg["session_id"] = sid_r
            roll_msg["roll"]["session_id"] = sid_r
        await manager.broadcast_nearby(
            character_id, roll_msg, include_self=False, respect_ignore=False
        )
        outbound.append(roll_msg)
        return character_id, user_id, outbound, None

    # --- Emotes (nearby + directed; shortcuts /wave /bow …) ---
    _EMOTE_SHORTCUTS = {
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
    if msg_type in (ClientMessageType.EMOTE, "emote", "emotes") or msg_type in _EMOTE_SHORTCUTS:
        allowed = set(_EMOTE_SHORTCUTS)
        raw_emote = data.get("emote")
        # Only treat id/action as emote name for generic emote msgs (not /wave + to_id)
        if msg_type not in _EMOTE_SHORTCUTS:
            if raw_emote is None:
                raw_emote = data.get("id")
            if raw_emote is None:
                raw_emote = data.get("action")
        # Top-level type shortcuts: {type:"wave", to:"Name"}
        if msg_type in _EMOTE_SHORTCUTS and (
            raw_emote is None
            or (isinstance(raw_emote, str) and not raw_emote.strip())
        ):
            raw_emote = msg_type
        # Bare /emotes or /emote list → catalog (no rate burn)
        want_list = (
            msg_type == "emotes"
            or data.get("list")
            or (
                isinstance(raw_emote, str)
                and raw_emote.strip().lower() in ("list", "help", "?", "emotes")
            )
        )
        if want_list:
            if character_id is not None:
                manager.touch(character_id)
            elist = sorted(allowed)
            outbound.append(
                msg(
                    "emotes",
                    emotes=elist,
                    message="Emotes: " + ", ".join(elist),
                )
            )
            return character_id, user_id, outbound, None
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        if raw_emote is None:
            raw_emote = "wave"  # bare {type:emote} defaults to wave
        if not isinstance(raw_emote, str):
            outbound.append(msg(ServerMessageType.ERROR, reason="bad emote"))
            return character_id, user_id, outbound, None
        emote = raw_emote.strip().lower()[:24]
        if not emote:
            outbound.append(msg(ServerMessageType.ERROR, reason="bad emote"))
            return character_id, user_id, outbound, None
        if emote not in allowed:
            outbound.append(msg(ServerMessageType.ERROR, reason="unknown emote"))
            return character_id, user_id, outbound, None
        # Combat is server-turn focused — no social emotes mid-fight
        if combat_engine.is_in_combat(character_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="in combat"))
            return character_id, user_id, outbound, None
        # Optional directed target — validate BEFORE rate limit (no AFK burn on fail)
        target_name = data.get("to") or data.get("name") or data.get("target") or data.get("player")
        # /wave @last · reply-style directed emote (server-tracked last target)
        want_last = bool(data.get("reply")) or (
            isinstance(target_name, str)
            and target_name.strip().lower() in ("@last", "last", "!")
        )
        # Prefer explicit to_id / player_id. For shortcuts only, `id` is a player id
        # (generic emote uses `id` as emote name — never as target).
        raw_pid = None
        if data.get("to_id") is not None:
            raw_pid = data.get("to_id")
        elif data.get("player_id") is not None:
            raw_pid = data.get("player_id")
        elif msg_type in _EMOTE_SHORTCUTS and data.get("id") is not None:
            raw_pid = data.get("id")
        target_id = (
            manager.find_id_by_player_id(raw_pid) if raw_pid is not None else None
        )
        tname: str | None = None
        # Explicit id that does not resolve → error (never fall through to undirected)
        if raw_pid is not None and target_id is None and not want_last:
            from network.websocket_manager import coerce_character_id

            if coerce_character_id(raw_pid) is None:
                outbound.append(msg(ServerMessageType.ERROR, reason="player not found"))
            else:
                outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        if want_last and target_id is None:
            lid, lname = manager.last_emote_to(character_id)
            if lid is None:
                outbound.append(msg(ServerMessageType.ERROR, reason="no one to emote"))
                return character_id, user_id, outbound, None
            target_id = lid
            target_name = lname
        if target_id is None and isinstance(target_name, str) and target_name.strip():
            # Skip name resolve when token is a last-emote sentinel
            if not want_last:
                tid, nerr = manager.resolve_live_name(target_name)
                if nerr == "name ambiguous":
                    outbound.append(msg(ServerMessageType.ERROR, reason="name ambiguous"))
                    return character_id, user_id, outbound, None
                if tid is None:
                    outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
                    return character_id, user_id, outbound, None
                target_id = tid
        if target_id is not None:
            if target_id == character_id:
                outbound.append(msg(ServerMessageType.ERROR, reason="cannot emote yourself"))
                return character_id, user_id, outbound, None
            if target_id not in manager.online_ids():
                outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
                return character_id, user_id, outbound, None
            # Same privacy model as whisper (before rate burn)
            if manager.is_ignored_by(target_id, character_id):
                outbound.append(msg(ServerMessageType.ERROR, reason="player unavailable"))
                return character_id, user_id, outbound, None
            if manager.is_ignored_by(character_id, target_id):
                outbound.append(msg(ServerMessageType.ERROR, reason="you ignore that player"))
                return character_id, user_id, outbound, None
            tmeta = manager.get_meta(target_id)
            tname = (tmeta or {}).get("name") or (
                target_name.strip() if isinstance(target_name, str) else "Hero"
            )
        meta = manager.get_meta(character_id)
        from network.websocket_manager import _is_idle as _idle_chk

        was_idle = _idle_chk(meta) if meta else False
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
        name = (meta or {}).get("name") or "Hero"
        emote_zone = None
        if meta is not None:
            try:
                emote_zone = zone_at(int(meta["x"]), int(meta["y"]))
            except Exception:
                emote_zone = None
        # Pretty multiplayer line for clients that ignore structured fields
        if tname:
            verb = {
                "wave": "waves at",
                "bow": "bows to",
                "cheer": "cheers for",
                "dance": "dances with",
                "cry": "cries with",
                "laugh": "laughs with",
                "point": "points at",
                "sit": "sits with",
                "think": "thinks of",
            }.get(emote, f"{emote}s at")
            emote_line = f"{name} {verb} {tname}"
        else:
            emote_line = None
        emote_msg = msg(
            ServerMessageType.EMOTE,
            player_id=character_id,
            name=name,
            emote=emote,
            x=(meta or {}).get("x"),
            y=(meta or {}).get("y"),
        )
        if emote_line:
            emote_msg["message"] = emote_line
            emote_msg["to"] = tname
            emote_msg["to_id"] = target_id
        if emote_zone in ("town", "field", "dungeon"):
            emote_msg["zone"] = emote_zone
        sid_e = manager.session_id(character_id)
        if sid_e is not None:
            emote_msg["session_id"] = sid_e
        # Peers via AOI; self via outbound (reliable single echo)
        await manager.broadcast_nearby(
            character_id, emote_msg, include_self=False, respect_ignore=True
        )
        # Directed: ensure target sees it even if outside AOI (never bypass ignore)
        if target_id is not None and target_id not in set(manager.ids_nearby(character_id)):
            if not manager.is_ignored_by(target_id, character_id):
                await manager.send(target_id, emote_msg)
        # Track last directed target for /wave @last (soft-grace)
        if target_id is not None and tname:
            manager.note_emote_to(character_id, target_id, tname)
        outbound.append(emote_msg)
        if was_idle:
            await manager.publish_status(character_id)
        return character_id, user_id, outbound, None

    # --- Use consumable (herb / wings / fairy water) ---
    if msg_type in (ClientMessageType.USE_ITEM, "use_item", "use", "consume"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        item_raw = data.get("item") or data.get("item_id")
        item_id, item_err = _resolve_item_arg(item_raw)
        if item_err or not item_id:
            outbound.append(
                msg(ServerMessageType.ERROR, reason=item_err or "item required")
            )
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

        # Successful use is multiplayer activity — clear AFK for peers
        was_afk_use = manager.mark_active(character_id)
        if was_afk_use:
            await manager.publish_status(character_id, pulse_online=True)

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
                await _announce_combat_outcome(character_id, str(battle.outcome))
                if battle.outcome == "defeat":
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
    if msg_type in (ClientMessageType.REST, "rest", "inn", "sleep"):
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
    if msg_type in (ClientMessageType.INVENTORY, "inventory", "bag", "inv", "items"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        outbound.append(await _inventory_msg(character_id))
        return character_id, user_id, outbound, None

    if msg_type in (ClientMessageType.SHOP, "shop", "store", "vendor"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        if combat_engine.is_in_combat(character_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="in combat"))
            return character_id, user_id, outbound, None
        meta = manager.get_meta(character_id)
        # Require live presence + town (was: missing meta skipped the town check)
        if not meta or zone_at(int(meta["x"]), int(meta["y"])) != "town":
            outbound.append(msg(ServerMessageType.ERROR, reason="shop only in town"))
            return character_id, user_id, outbound, None
        manager.touch(character_id)
        outbound.append(msg(ServerMessageType.SHOP_LIST, items=shop_catalog()))
        return character_id, user_id, outbound, None

    if msg_type in (ClientMessageType.EQUIP, "equip", "wear", "wield"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        if combat_engine.is_in_combat(character_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="in combat"))
            return character_id, user_id, outbound, None
        slot = data.get("slot")
        item_raw = data.get("item") or data.get("item_id")
        item_id, item_err = _resolve_item_arg(item_raw) if item_raw else (None, "item required")
        if item_err or not item_id:
            outbound.append(
                msg(ServerMessageType.ERROR, reason=item_err or "item required")
            )
            return character_id, user_id, outbound, None
        # Auto-slot from equipment def when client only sends item (slash /equip club)
        if (not slot or not str(slot).strip()) and item_id:
            from game.item_manager import get_equipment_def

            defn = get_equipment_def(str(item_id).strip())
            if defn and defn.get("slot"):
                slot = defn.get("slot")
        char = await get_character(character_id)
        if not char:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            return character_id, user_id, outbound, None
        async with db_write() as db:
            ok, reason = await equip_item(db, char, str(slot or ""), str(item_id or ""))
        if not ok:
            outbound.append(msg(ServerMessageType.ERROR, reason=reason))
            return character_id, user_id, outbound, None
        was_afk = manager.mark_active(character_id)
        if was_afk:
            await manager.publish_status(character_id, pulse_online=True)
        inv = await _inventory_msg(character_id)
        inv["equipped"] = {"slot": str(slot or ""), "item_id": str(item_id or "")}
        inv["message"] = f"Equipped {item_id}."
        outbound.append(inv)
        return character_id, user_id, outbound, None

    if msg_type in (
        ClientMessageType.UNEQUIP,
        "unequip",
        "takeoff",
        "remove",
    ):
        if combat_engine.is_in_combat(character_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="in combat"))
            return character_id, user_id, outbound, None
        slot = data.get("slot")
        char = await get_character(character_id)
        if not char:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            return character_id, user_id, outbound, None
        # Remember what was equipped for the toast (unequip mutates char)
        from game.item_manager import SLOT_COLUMNS

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
        inv = await _inventory_msg(character_id)
        inv["unequipped"] = {"slot": slot_s, "item_id": prev_id}
        inv["message"] = (
            f"Unequipped {prev_id}." if prev_id else f"Unequipped {slot_s}."
        )
        outbound.append(inv)
        return character_id, user_id, outbound, None

    # Discard / drop from bag (destroy — free a slot when bag is full)
    if msg_type in ("discard", "drop", "destroy", "throw_away"):
        if combat_engine.is_in_combat(character_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="in combat"))
            return character_id, user_id, outbound, None
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
        inv = await _inventory_msg(character_id)
        inv["discarded"] = info
        inv["message"] = (
            f"Discarded {info.get('quantity', 1)}× "
            f"{info.get('item_name') or item_id}"
        )
        outbound.append(inv)
        return character_id, user_id, outbound, None

    if msg_type in (ClientMessageType.BUY, "buy", "purchase"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        if combat_engine.is_in_combat(character_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="in combat"))
            return character_id, user_id, outbound, None
        meta = manager.get_meta(character_id)
        if not meta or zone_at(int(meta["x"]), int(meta["y"])) != "town":
            outbound.append(msg(ServerMessageType.ERROR, reason="shop only in town"))
            return character_id, user_id, outbound, None
        item_raw = data.get("item") or data.get("item_id")
        item_id, item_err = _resolve_item_arg(item_raw)
        if item_err or not item_id:
            outbound.append(
                msg(ServerMessageType.ERROR, reason=item_err or "item required")
            )
            return character_id, user_id, outbound, None
        # quantity: never use `or 1` — qty=0 must not buy one unit
        if "quantity" in data:
            raw_qty = data.get("quantity")
        elif "qty" in data:
            raw_qty = data.get("qty")
        else:
            raw_qty = 1
        buy_qty = _parse_positive_qty(raw_qty)
        if buy_qty is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="bad quantity"))
            return character_id, user_id, outbound, None
        char = await get_character(character_id)
        if not char:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            return character_id, user_id, outbound, None
        async with db_write() as db:
            ok, reason, bought = await buy_item(
                db, char, str(item_id).strip(), quantity=buy_qty
            )
        if not ok:
            # Surface cost when short on gold (mirrors inn not-enough path)
            err = msg(ServerMessageType.ERROR, reason=reason)
            if bought.get("cost") is not None:
                err["cost"] = bought["cost"]
            if bought.get("gold") is not None:
                err["gold"] = bought["gold"]
            # Bag-full paths: include current bag snapshot for client tips
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
        outbound.append(inv)
        return character_id, user_id, outbound, None

    if msg_type in (ClientMessageType.SELL, "sell", "vendor_sell"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        if combat_engine.is_in_combat(character_id):
            outbound.append(msg(ServerMessageType.ERROR, reason="in combat"))
            return character_id, user_id, outbound, None
        meta = manager.get_meta(character_id)
        if not meta or zone_at(int(meta["x"]), int(meta["y"])) != "town":
            outbound.append(msg(ServerMessageType.ERROR, reason="shop only in town"))
            return character_id, user_id, outbound, None
        item_raw = data.get("item") or data.get("item_id")
        item_id, item_err = _resolve_item_arg(item_raw)
        if item_err or not item_id:
            outbound.append(
                msg(ServerMessageType.ERROR, reason=item_err or "item required")
            )
            return character_id, user_id, outbound, None
        # quantity: never use `or 1` — qty=0 must not sell one unit
        if "quantity" in data:
            raw_qty = data.get("quantity")
        elif "qty" in data:
            raw_qty = data.get("qty")
        else:
            raw_qty = 1
        sell_qty = _parse_positive_qty(raw_qty)
        if sell_qty is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="bad quantity"))
            return character_id, user_id, outbound, None
        char = await get_character(character_id)
        if not char:
            outbound.append(msg(ServerMessageType.ERROR, reason="character missing"))
            return character_id, user_id, outbound, None
        async with db_write() as db:
            ok, reason, sold = await sell_item(
                db, char, str(item_id).strip(), quantity=sell_qty
            )
        if not ok:
            outbound.append(msg(ServerMessageType.ERROR, reason=reason))
            return character_id, user_id, outbound, None
        was_afk = manager.mark_active(character_id)
        if was_afk:
            await manager.publish_status(character_id, pulse_online=True)
        inv = await _inventory_msg(character_id)
        # Surface sell result so clients can toast gold earned
        if sold:
            inv["sold"] = sold
            q = int(sold.get("quantity") or 1)
            inv["message"] = (
                f"Sold {q}× {sold.get('item_name') or item_id} "
                f"for {sold.get('gold_gained', 0)} G"
                if q > 1
                else f"Sold {sold.get('item_name') or item_id} for {sold.get('gold_gained', 0)} G"
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
        hero_nm = (manager.get_meta(character_id) or {}).get("name") or "Hero"
        await manager.broadcast_nearby(
            character_id,
            msg(
                ServerMessageType.CHAT,
                player_id=character_id,
                name="System",
                text=f"{hero_nm} is fighting!",
                channel="system",
                system=True,
            ),
            include_self=False,
            respect_ignore=False,
        )
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
