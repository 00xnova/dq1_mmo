import math
import re
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
from network.handlers import afk as afk_handlers
from network.handlers import askwhere as askwhere_handlers
from network.handlers import find as find_handlers
from network.handlers import hud_info as hud_info_handlers
from network.handlers import emote as emote_handlers
from network.handlers import invite as invite_handlers
from network.handlers import invite_cancel as invite_cancel_handlers
from network.handlers import invite_reply as invite_reply_handlers
from network.handlers import whisper as whisper_handlers
from network.handlers import look as look_handlers
from network.handlers import meta_peeks as meta_peek_handlers
from network.handlers import mute as mute_handlers
from network.handlers import poke as poke_handlers
from network.handlers import presence_peeks
from network.handlers import roll as roll_handlers
from network.handlers import safety as safety_handlers
from network.handlers import self_peeks as self_peek_handlers
from network.handlers import session as session_handlers
from network.handlers import share as share_handlers
from network.handlers import social_peeks
from network.handlers import status as status_handlers
from network.handlers import thank as thank_handlers
from network.handlers._common import (  # noqa: F401 — re-export for tests
    _afk_snap,
    _announce_combat_outcome,
    _combat_update,
    _format_uptime,
    _inventory_msg,
    _parse_positive_qty,
    _persist_battle_end,
    _resolve_item_arg,
    _resolve_social_peer,
    _social_alias,
    best_effort_send,
    peer_status_suffix,
    private_social_delivery,
    sanitize_chat,
    social_peer_card,
)
from network.protocol import ClientMessageType, ServerMessageType, msg
from network.websocket_manager import CHAT_MAX_LEN, manager


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


async def handle_message(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
) -> tuple[int | None, int | None, list[dict], dict | None]:
    msg_type = data.get("type")
    outbound: list[dict] = []
    connect_meta: dict | None = None

    if msg_type in session_handlers.PING_TYPES or msg_type == ClientMessageType.PING:
        return await session_handlers.handle_ping(
            character_id, user_id, data, outbound
        )

    if msg_type in session_handlers.SYNC_TYPES:
        return await session_handlers.handle_sync(
            character_id, user_id, data, outbound
        )

    social_peek = await social_peeks.handle(
        character_id, user_id, data, outbound
    )
    if social_peek is not None:
        return social_peek

    look_peek = await look_handlers.handle(
        character_id, user_id, data, outbound
    )
    if look_peek is not None:
        return look_peek

    status_peek = await status_handlers.handle(
        character_id, user_id, data, outbound
    )
    if status_peek is not None:
        return status_peek

    self_peek = await self_peek_handlers.handle(
        character_id, user_id, data, outbound
    )
    if self_peek is not None:
        return self_peek

    meta_peek = await meta_peek_handlers.handle(
        character_id, user_id, data, outbound
    )
    if meta_peek is not None:
        return meta_peek

    presence_peek = await presence_peeks.handle(
        character_id, user_id, data, outbound
    )
    if presence_peek is not None:
        return presence_peek

    mute_peek = await mute_handlers.handle(
        character_id, user_id, data, outbound
    )
    if mute_peek is not None:
        return mute_peek

    hud_peek = await hud_info_handlers.handle(
        character_id, user_id, data, outbound
    )
    if hud_peek is not None:
        return hud_peek

    afk_peek = await afk_handlers.handle(
        character_id, user_id, data, outbound
    )
    if afk_peek is not None:
        return afk_peek

    safety_peek = await safety_handlers.handle(
        character_id, user_id, data, outbound
    )
    if safety_peek is not None:
        return safety_peek

    find_peek = await find_handlers.handle(
        character_id, user_id, data, outbound
    )
    if find_peek is not None:
        return find_peek

    roll_peek = await roll_handlers.handle(
        character_id, user_id, data, outbound
    )
    if roll_peek is not None:
        return roll_peek

    poke_peek = await poke_handlers.handle(
        character_id, user_id, data, outbound
    )
    if poke_peek is not None:
        return poke_peek

    thank_peek = await thank_handlers.handle(
        character_id, user_id, data, outbound
    )
    if thank_peek is not None:
        return thank_peek

    askwhere_peek = await askwhere_handlers.handle(
        character_id, user_id, data, outbound
    )
    if askwhere_peek is not None:
        return askwhere_peek

    share_peek = await share_handlers.handle(
        character_id, user_id, data, outbound
    )
    if share_peek is not None:
        return share_peek

    cancel_peek = await invite_cancel_handlers.handle(
        character_id, user_id, data, outbound
    )
    if cancel_peek is not None:
        return cancel_peek

    invite_peek = await invite_handlers.handle(
        character_id, user_id, data, outbound
    )
    if invite_peek is not None:
        return invite_peek

    reply_peek = await invite_reply_handlers.handle(
        character_id, user_id, data, outbound
    )
    if reply_peek is not None:
        return reply_peek

    emote_peek = await emote_handlers.handle(
        character_id, user_id, data, outbound
    )
    if emote_peek is not None:
        return emote_peek

    whisper_peek = await whisper_handlers.handle(
        character_id, user_id, data, outbound
    )
    if whisper_peek is not None:
        return whisper_peek

    # peeks + social private + invite/emote/whisper via handlers

    # fighting via presence_peeks · quit/stuck via safety

    # version / played / time via meta_peeks · ignore/unignore/ignores via mute

    # find handled via network.handlers.find

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

    # whisper/tell/reply via network.handlers.whisper

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
            social_mode_w = _social_alias(target_name, data)
            target_id = manager.find_id_by_player_id(
                data.get("to_id") or data.get("player_id") or data.get("id")
            )
            if social_mode_w and target_id is None:
                chain_w = (
                    ("whisper", "emote", "invite_from", "invite_to")
                    if social_mode_w == "last"
                    else ("invite_from", "invite_to")
                )
                lid_w, lname_w, empty_w = _resolve_social_peer(
                    manager, character_id, social_mode_w, chain=chain_w
                )
                if lid_w is None:
                    outbound.append(
                        msg(
                            ServerMessageType.ERROR,
                            reason=empty_w
                            if social_mode_w == "pending"
                            else "no one to reply to",
                        )
                    )
                    return character_id, user_id, outbound, None
                target_id = lid_w
                target_name = lname_w
            if target_id is None and isinstance(target_name, str) and target_name.strip():
                if not social_mode_w:
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
            if not await private_social_delivery(
                character_id,
                target_id,
                whisper_msg,
                was_afk=was_afk_w,
                afk_message=afk_msg_w,
                outbound=outbound,
            ):
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

    # roll/dice · emotes via network.handlers

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
