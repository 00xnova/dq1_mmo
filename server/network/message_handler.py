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
from network.handlers import hud_info as hud_info_handlers
from network.handlers import look as look_handlers
from network.handlers import meta_peeks as meta_peek_handlers
from network.handlers import mute as mute_handlers
from network.handlers import presence_peeks
from network.handlers import self_peeks as self_peek_handlers
from network.handlers import session as session_handlers
from network.handlers import social_peeks
from network.handlers import status as status_handlers
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

    # who/near · look · status · gold · version · mute · keys/help · afk via handlers

    # Social peeks (lastwhisper/social/lastemote/lastshare/lastinvite/pending)
    # handled early via network.handlers.social_peeks

    # --- Meetup invite (lightweight multiplayer social — not a party) ---
    if msg_type in ("invite", "meet", "beckon", "come"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        target_name = data.get("to") or data.get("name") or data.get("target") or data.get("player")
        social_mode = _social_alias(target_name, data)
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
        if social_mode and target_id is None:
            # @last: whisper/emote; @pending: meetup peer (invite back / re-send)
            chain = (
                ("whisper", "emote")
                if social_mode == "last"
                else ("invite_from", "invite_to")
            )
            lid, lname, empty = _resolve_social_peer(
                manager, character_id, social_mode, chain=chain
            )
            if lid is None:
                outbound.append(
                    msg(
                        ServerMessageType.ERROR,
                        reason=empty or "no one to invite",
                    )
                )
                return character_id, user_id, outbound, None
            target_id = lid
            target_name = lname
        if target_id is None and isinstance(target_name, str) and target_name.strip():
            if not social_mode:
                tid, nerr = manager.resolve_live_name(target_name)
                if nerr == "name ambiguous":
                    outbound.append(msg(ServerMessageType.ERROR, reason="name ambiguous"))
                    return character_id, user_id, outbound, None
                target_id = tid
        if target_id is None:
            if not (
                isinstance(target_name, str) and target_name.strip()
            ) and raw_pid is None and not social_mode:
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
        if not await private_social_delivery(
            character_id,
            target_id,
            invite_msg,
            was_afk=was_afk,
            afk_message=afk_msg_snap,
            outbound=outbound,
        ):
            return character_id, user_id, outbound, None
        # Both sides track social peer for /r · /thank @last after invite
        manager.note_whisper_from(character_id, target_id, tname)
        manager.note_whisper_from(target_id, character_id, name)
        # Target remembers inviter for /accept · /lastinvite (soft-grace)
        prev_inviter = manager.note_invite_from(target_id, character_id, name)
        # Inviter remembers target for /cancel
        prev_guest = manager.note_invite_to(character_id, target_id, tname)
        # Multiplayer hygiene: notify peers whose pending invite was replaced
        if prev_inviter is not None and prev_inviter in manager.online_ids():
            # Informational about the guest — still skip if they muted us (no spam)
            if not manager.is_ignored_by(prev_inviter, character_id):
                sup: dict[str, Any] = {
                    "type": "invite_superseded",
                    "to": tname,
                    "to_id": target_id,
                    "message": f"{tname} received another meetup invite.",
                }
                sid_sup = manager.session_id(character_id)
                if sid_sup is not None:
                    sup["session_id"] = sid_sup
                await best_effort_send(prev_inviter, sup)
        if prev_guest is not None and prev_guest in manager.online_ids():
            # Respect ignore: do not push cancel toast to someone who muted us
            if not manager.is_ignored_by(prev_guest, character_id):
                prev_meta = manager.get_meta(prev_guest)
                prev_name = (prev_meta or {}).get("name") or "Hero"
                retarget_msg: dict[str, Any] = {
                    "type": "invite_cancel",
                    "from": name,
                    "from_id": character_id,
                    "to": prev_name,
                    "to_id": prev_guest,
                    "message": f"{name} cancelled their meetup invite.",
                    "reason": "retarget",
                }
                sid_rt = manager.session_id(character_id)
                if sid_rt is not None:
                    retarget_msg["session_id"] = sid_rt
                await best_effort_send(prev_guest, retarget_msg)
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
        muted_skip = False
        peer_near: bool | None = None
        if tid in manager.online_ids():
            tmeta = manager.get_meta(tid)
            live_name = (tmeta or {}).get("name") or tname or "Hero"
            peer_near = tid in set(manager.ids_nearby(character_id))
            # Only notify if invite is still pending from us
            # (prevents spam cancel after accept/decline)
            from_id, _ = manager.last_invite_from(tid)
            if from_id == character_id:
                # Do not push cancel to someone who ignores us (mute hygiene)
                if not manager.is_ignored_by(tid, character_id):
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
                    # Honest notified flag — dead sockets must not claim success
                    notified = await best_effort_send(tid, cancel_msg)
                else:
                    muted_skip = True
                # still clear their pending pointer even if muted / send failed
        # Always drop peer pointer (live + soft-grace) so offline guests
        # do not rehydrate a zombie invite after reconnect.
        manager.clear_invite_from_peer(tid, character_id)
        manager.clear_last_invite_to(character_id)
        if notified:
            clear_msg = f"Invite to {live_name} cancelled."
        elif muted_skip:
            clear_msg = f"Cleared invite to {live_name} (they muted you)."
        else:
            clear_msg = f"Cleared invite to {live_name} (already answered or offline)."
        cancel_echo: dict[str, Any] = {
            "type": "invite_cancel",
            "action": "cancel",
            "to": live_name,
            "to_id": tid,
            "notified": notified,
            "muted": muted_skip,
            "message": clear_msg,
        }
        if peer_near is not None:
            cancel_echo["nearby"] = peer_near
        outbound.append(cancel_echo)
        if was_idle:
            await manager.publish_status(character_id)
        return character_id, user_id, outbound, None

    # --- Private location share (meetup helper — always opt-in) ---
    if msg_type in ("share", "sharepos", "share_pos", "whereami_share", "here_i_am"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        target_name = data.get("to") or data.get("name") or data.get("target") or data.get("player")
        social_mode = _social_alias(target_name, data)
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
        if social_mode and target_id is None:
            lid, lname, empty = _resolve_social_peer(manager, character_id, social_mode)
            if lid is None:
                outbound.append(
                    msg(
                        ServerMessageType.ERROR,
                        reason=empty if social_mode in ("pending", "share", "share_from", "emote", "emote_from") else "no one to share with",
                    )
                )
                return character_id, user_id, outbound, None
            target_id = lid
            target_name = lname
        if target_id is None and isinstance(target_name, str) and target_name.strip():
            if not social_mode:
                tid, nerr = manager.resolve_live_name(target_name)
                if nerr == "name ambiguous":
                    outbound.append(msg(ServerMessageType.ERROR, reason="name ambiguous"))
                    return character_id, user_id, outbound, None
                target_id = tid
        if target_id is None:
            if not (
                isinstance(target_name, str) and target_name.strip()
            ) and raw_pid is None and not social_mode:
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
        if not await private_social_delivery(
            character_id,
            target_id,
            share_msg,
            was_afk=was_afk,
            afk_message=afk_msg_snap,
            outbound=outbound,
        ):
            return character_id, user_id, outbound, None
        manager.note_whisper_from(character_id, target_id, tname)
        manager.note_whisper_from(target_id, character_id, name)
        manager.note_share_to(character_id, target_id, tname)
        # Recipient remembers sharer for /thank @share · /lastshare after reconnect
        manager.note_share_from(target_id, character_id, name)
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
        social_mode = _social_alias(target_name, data)
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
        if social_mode and target_id is None:
            lid, lname, empty = _resolve_social_peer(manager, character_id, social_mode)
            if lid is None:
                outbound.append(
                    msg(
                        ServerMessageType.ERROR,
                        reason=empty if social_mode in ("pending", "share", "share_from", "emote", "emote_from") else "no one to poke",
                    )
                )
                return character_id, user_id, outbound, None
            target_id = lid
            target_name = lname
        if target_id is None and isinstance(target_name, str) and target_name.strip():
            if not social_mode:
                tid, nerr = manager.resolve_live_name(target_name)
                if nerr == "name ambiguous":
                    outbound.append(msg(ServerMessageType.ERROR, reason="name ambiguous"))
                    return character_id, user_id, outbound, None
                target_id = tid
        if target_id is None:
            if not (
                isinstance(target_name, str) and target_name.strip()
            ) and raw_pid is None and not social_mode:
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
        if not await private_social_delivery(
            character_id,
            target_id,
            poke_msg,
            was_afk=was_afk,
            afk_message=afk_msg_snap,
            outbound=outbound,
        ):
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
        social_mode = _social_alias(target_name, data)
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
        if social_mode and target_id is None:
            lid, lname, empty = _resolve_social_peer(manager, character_id, social_mode)
            if lid is None:
                outbound.append(
                    msg(
                        ServerMessageType.ERROR,
                        reason=empty if social_mode in ("pending", "share", "share_from", "emote", "emote_from") else "no one to ask",
                    )
                )
                return character_id, user_id, outbound, None
            target_id = lid
            target_name = lname
        if target_id is None and isinstance(target_name, str) and target_name.strip():
            if not social_mode:
                tid, nerr = manager.resolve_live_name(target_name)
                if nerr == "name ambiguous":
                    outbound.append(msg(ServerMessageType.ERROR, reason="name ambiguous"))
                    return character_id, user_id, outbound, None
                target_id = tid
        if target_id is None:
            if not (
                isinstance(target_name, str) and target_name.strip()
            ) and raw_pid is None and not social_mode:
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
        if not await private_social_delivery(
            character_id,
            target_id,
            req_msg,
            was_afk=was_afk,
            afk_message=afk_msg_snap,
            outbound=outbound,
        ):
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

    # --- Thank (private multiplayer ack — e.g. after /share) ---
    if msg_type in ("thank", "thanks", "ty", "thx", "thankyou", "thank_you"):
        if character_id is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
            return character_id, user_id, outbound, None
        target_name = data.get("to") or data.get("name") or data.get("target") or data.get("player")
        social_mode = _social_alias(target_name, data)
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
        if social_mode and target_id is None:
            lid, lname, empty = _resolve_social_peer(manager, character_id, social_mode)
            if lid is None:
                outbound.append(
                    msg(
                        ServerMessageType.ERROR,
                        reason=empty if social_mode in ("pending", "share", "share_from", "emote", "emote_from") else "no one to thank",
                    )
                )
                return character_id, user_id, outbound, None
            target_id = lid
            target_name = lname
        if target_id is None and isinstance(target_name, str) and target_name.strip():
            if not social_mode:
                tid, nerr = manager.resolve_live_name(target_name)
                if nerr == "name ambiguous":
                    outbound.append(msg(ServerMessageType.ERROR, reason="name ambiguous"))
                    return character_id, user_id, outbound, None
                target_id = tid
        if target_id is None:
            if not (
                isinstance(target_name, str) and target_name.strip()
            ) and raw_pid is None and not social_mode:
                outbound.append(msg(ServerMessageType.ERROR, reason="thank target required"))
            else:
                outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        if target_id == character_id:
            outbound.append(msg(ServerMessageType.ERROR, reason="cannot thank yourself"))
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
        thank_line = f"{name} thanks you."
        thank_msg: dict = {
            "type": "thank",
            "from": name,
            "from_id": character_id,
            "to": tname,
            "to_id": target_id,
            "message": thank_line,
        }
        sid_t = manager.session_id(character_id)
        if sid_t is not None:
            thank_msg["session_id"] = sid_t
        if not await private_social_delivery(
            character_id,
            target_id,
            thank_msg,
            was_afk=was_afk,
            afk_message=afk_msg_snap,
            outbound=outbound,
        ):
            return character_id, user_id, outbound, None
        manager.note_whisper_from(character_id, target_id, tname)
        manager.note_whisper_from(target_id, character_id, name)
        echo = dict(thank_msg)
        echo["message"] = f"You thanked {tname}."
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

    # lastinvite / pending peeks handled via network.handlers.social_peeks

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
            # Inviter left — clear stuck invite so /accept|/decline cannot loop forever
            # Also clear inviter soft-grace last_invite_to so they do not rehydrate
            # a zombie outgoing invite after reconnect.
            manager.clear_last_invite(character_id)
            manager.clear_invite_to_peer(lid, character_id)
            live = lname or "Hero"
            outbound.append(
                msg(
                    ServerMessageType.ERROR,
                    reason="player not online",
                    invite_cleared=True,
                    message=f"Invite from {live} cleared (player offline).",
                )
            )
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
        # Zone of the person accepting/declining (no coords unless already nearby)
        from network.websocket_manager import _zone_of

        reply_zone = _zone_of(meta) if meta else None
        zone_bit = (
            f" (from the {reply_zone})"
            if reply_zone in ("town", "field", "dungeon")
            else ""
        )
        if accepting:
            line = f"{name} is coming to meet you{zone_bit}."
            self_line = f"You told {tname} you are coming{zone_bit}."
            action = "accept"
        else:
            line = f"{name} cannot meet right now{zone_bit}."
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
        if reply_zone in ("town", "field", "dungeon"):
            reply_msg["zone"] = reply_zone
        # Share coords only when already nearby (same privacy as invite/look)
        if lid in set(manager.ids_nearby(character_id)):
            try:
                reply_msg["x"] = int(meta["x"]) if meta else None
                reply_msg["y"] = int(meta["y"]) if meta else None
            except (TypeError, ValueError, KeyError):
                pass
            reply_msg["nearby"] = True
        else:
            reply_msg["nearby"] = False
        sid_r = manager.session_id(character_id)
        if sid_r is not None:
            reply_msg["session_id"] = sid_r
        if not await private_social_delivery(
            character_id,
            lid,
            reply_msg,
            was_afk=was_afk,
            afk_message=afk_msg_snap,
            outbound=outbound,
        ):
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

    # fighting handled via network.handlers.presence_peeks

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

    # version / played / time via meta_peeks · ignore/unignore/ignores via mute

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
        # Pull ALL zone:/in:, afk:, idle:, combat: tokens from free text.
        # Loop until none remain — leftover tokens used to become a name prefix
        # (e.g. "zone:town zone:field" → 0 hits). Last token of each kind wins.
        if isinstance(q_clean, str) and q_clean:
            for _ in range(12):  # hard cap; filters are tiny
                progressed = False
                m_zone = re.search(
                    r"(?:^|\s)(?:zone|in):(\w+)\b", q_clean, flags=re.I
                )
                if m_zone:
                    zone_f = m_zone.group(1)
                    q_clean = (
                        q_clean[: m_zone.start()] + q_clean[m_zone.end() :]
                    ).strip()
                    progressed = True
                m_afk = re.search(r"(?:^|\s)afk:(\w+)\b", q_clean, flags=re.I)
                if m_afk:
                    tok = m_afk.group(1).lower()
                    if tok not in ("yes", "no", "1", "0", "true", "false"):
                        outbound.append(
                            msg(ServerMessageType.ERROR, reason="invalid afk filter")
                        )
                        return character_id, user_id, outbound, None
                    afk_f = tok in ("yes", "1", "true")
                    q_clean = (
                        q_clean[: m_afk.start()] + q_clean[m_afk.end() :]
                    ).strip()
                    progressed = True
                m_idle = re.search(r"(?:^|\s)idle:(\w+)\b", q_clean, flags=re.I)
                if m_idle:
                    tok = m_idle.group(1).lower()
                    if tok not in ("yes", "no", "1", "0", "true", "false"):
                        outbound.append(
                            msg(ServerMessageType.ERROR, reason="invalid idle filter")
                        )
                        return character_id, user_id, outbound, None
                    idle_f = tok in ("yes", "1", "true")
                    q_clean = (
                        q_clean[: m_idle.start()] + q_clean[m_idle.end() :]
                    ).strip()
                    progressed = True
                m_combat = re.search(
                    r"(?:^|\s)(?:combat|fighting):(\w+)\b", q_clean, flags=re.I
                )
                if m_combat:
                    tok = m_combat.group(1).lower()
                    if tok not in ("yes", "no", "1", "0", "true", "false"):
                        outbound.append(
                            msg(
                                ServerMessageType.ERROR,
                                reason="invalid combat filter",
                            )
                        )
                        return character_id, user_id, outbound, None
                    combat_f = tok in ("yes", "1", "true")
                    q_clean = (
                        q_clean[: m_combat.start()] + q_clean[m_combat.end() :]
                    ).strip()
                    progressed = True
                if not progressed:
                    break
            # Collapse whitespace after multi-strip
            q_clean = re.sub(r"\s+", " ", q_clean).strip()
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
        # Multiplayer social aliases: /find @pending · /find @last
        social_q = _social_alias(q_clean)
        if social_q:
            lid, lname, empty = _resolve_social_peer(manager, character_id, social_q)
            if lid is None:
                outbound.append(
                    msg(
                        ServerMessageType.ERROR,
                        reason=empty
                        if social_q in ("pending", "share", "share_from", "emote", "emote_from")
                        else "no one to find",
                    )
                )
                return character_id, user_id, outbound, None
            if lid not in manager.online_ids():
                outbound.append(
                    msg(ServerMessageType.ERROR, reason="player not online")
                )
                return character_id, user_id, outbound, None
            from network.websocket_manager import _online_card

            pmeta = manager.get_meta(lid)
            if pmeta is None:
                outbound.append(
                    msg(ServerMessageType.ERROR, reason="player not online")
                )
                return character_id, user_id, outbound, None
            card = _online_card(pmeta)
            # Apply optional filters to the single peer
            peer_name = str(card.get("name") or lname or "Hero")
            peer_zone = card.get("zone") if isinstance(card.get("zone"), str) else None
            filtered_out = False
            filter_why: str | None = None
            if zone_f and card.get("zone") != zone_f:
                hits = []
                filtered_out = True
                filter_why = f"zone:{zone_f}"
            elif afk_filter is not None and bool(card.get("afk")) is not bool(afk_filter):
                hits = []
                filtered_out = True
                filter_why = "afk:" + ("yes" if afk_filter else "no")
            elif idle_filter is not None and bool(card.get("idle")) is not bool(
                idle_filter
            ):
                hits = []
                filtered_out = True
                filter_why = "idle:" + ("yes" if idle_filter else "no")
            elif combat_filter is not None and bool(card.get("in_combat")) is not bool(
                combat_filter
            ):
                hits = []
                filtered_out = True
                filter_why = "combat:" + ("yes" if combat_filter else "no")
            else:
                hits = [card]
            q_clean = (
                "@pending"
                if social_q in ("pending", "share", "share_from", "emote", "emote_from")
                else ("@last" if social_q == "last" else f"@{social_q}")
            )
        else:
            hits = manager.find_by_prefix(
                q_clean,
                limit=limit_i,
                zone=zone_f,
                afk=afk_filter,
                idle=idle_filter,
                combat=combat_filter,
            )
            # Tag self so clients can highlight "you" without dropping self-hits
            if character_id is not None and hits:
                for card in hits:
                    try:
                        if int(card.get("id") or 0) == int(character_id):
                            card["you"] = True
                    except (TypeError, ValueError):
                        continue
            filtered_out = False
            filter_why = None
            peer_name = None
            peer_zone = None
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
        find_msg_extra: dict = {}
        if filtered_out and peer_name:
            find_msg_extra["filtered"] = True
            find_msg_extra["filtered_peer"] = peer_name
            if filter_why:
                find_msg_extra["filter"] = filter_why
            if peer_zone:
                find_msg_extra["peer_zone"] = peer_zone
            # Human-readable hint so clients don't show a blank "0 matches"
            where = f" in {peer_zone}" if peer_zone else ""
            find_msg_extra["message"] = (
                f"{peer_name} online{where} but filtered out"
                f" ({filter_why or 'filter'})"
            )
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
                **find_msg_extra,
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
        "r",  # short alias (client usually maps /r → reply; raw type also OK)
    ):
        text = sanitize_chat(data.get("text") or data.get("message") or data.get("msg"))
        if text is None:
            outbound.append(msg(ServerMessageType.ERROR, reason="empty chat"))
            return character_id, user_id, outbound, None
        # Server-side reply / social aliases (@last · @pending)
        target_name = data.get("to") or data.get("name") or data.get("target") or data.get("player")
        is_reply_cmd = msg_type in (ClientMessageType.REPLY, "reply", "r")
        social_mode = _social_alias(target_name, data)
        if is_reply_cmd and social_mode is None:
            social_mode = "last"
        if social_mode is None and bool(data.get("reply")):
            social_mode = "last"
        if social_mode is None and (
            target_name is None or (isinstance(target_name, str) and not target_name.strip())
        ) and is_reply_cmd:
            social_mode = "last"
        target_id = None
        if social_mode:
            # reply/@last: whisper peer first; @pending: meetup peer
            chain = (
                ("whisper", "emote", "invite_from", "invite_to")
                if social_mode == "last"
                else ("invite_from", "invite_to")
            )
            if social_mode == "last" and is_reply_cmd:
                chain = ("whisper", "invite_from", "invite_to", "emote")
            lid, lname, empty = _resolve_social_peer(
                manager, character_id, social_mode, chain=chain
            )
            if lid is None:
                if social_mode in ("share", "share_from", "emote", "emote_from"):
                    reason = empty or {
                        "share": "no share target",
                        "share_from": "no share from anyone",
                        "emote": "no emote target",
                        "emote_from": "no one emoted at you",
                    }.get(social_mode, "no one")
                elif is_reply_cmd or social_mode == "last":
                    reason = "no one to reply to"
                else:
                    reason = empty or "no pending invite"
                outbound.append(msg(ServerMessageType.ERROR, reason=reason))
                return character_id, user_id, outbound, None
            target_id = lid
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
        if not await private_social_delivery(
            character_id,
            target_id,
            whisper_msg,
            was_afk=was_afk,
            afk_message=afk_msg_snap,
            outbound=outbound,
        ):
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
        # /wave @last · @pending · reply-style directed emote
        social_mode = _social_alias(target_name, data)
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
        if raw_pid is not None and target_id is None and not social_mode:
            from network.websocket_manager import coerce_character_id

            if coerce_character_id(raw_pid) is None:
                outbound.append(msg(ServerMessageType.ERROR, reason="player not found"))
            else:
                outbound.append(msg(ServerMessageType.ERROR, reason="player not online"))
            return character_id, user_id, outbound, None
        if social_mode and target_id is None:
            chain = (
                ("emote", "whisper", "invite_from", "invite_to")
                if social_mode == "last"
                else ("invite_from", "invite_to")
            )
            lid, lname, empty = _resolve_social_peer(
                manager, character_id, social_mode, chain=chain
            )
            if lid is None:
                outbound.append(
                    msg(
                        ServerMessageType.ERROR,
                        reason=empty if social_mode in ("pending", "share", "share_from", "emote", "emote_from") else "no one to emote",
                    )
                )
                return character_id, user_id, outbound, None
            target_id = lid
            target_name = lname
        if target_id is None and isinstance(target_name, str) and target_name.strip():
            # Skip name resolve when token is a social alias sentinel
            if not social_mode:
                tid, nerr = manager.resolve_live_name(target_name)
                if nerr == "name ambiguous":
                    outbound.append(msg(ServerMessageType.ERROR, reason="name ambiguous"))
                    return character_id, user_id, outbound, None
                target_id = tid
                # Explicit directed name that does not resolve must not fall through
                # to an undirected emote (multiplayer reliability).
                if target_id is None:
                    outbound.append(
                        msg(ServerMessageType.ERROR, reason="player not online")
                    )
                    return character_id, user_id, outbound, None
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
        # Snap AFK before allow_chat so far directed delivery can restore on fail
        was_afk, afk_msg_snap = _afk_snap(meta)
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
        # Directed far: private delivery must succeed or refund chat (not a silent lie)
        if target_id is not None and target_id not in set(manager.ids_nearby(character_id)):
            if not manager.is_ignored_by(target_id, character_id):
                if not await private_social_delivery(
                    character_id,
                    target_id,
                    emote_msg,
                    was_afk=was_afk,
                    afk_message=afk_msg_snap,
                    outbound=outbound,
                ):
                    return character_id, user_id, outbound, None
        # Track last directed target + recipient memory (soft-grace)
        if target_id is not None and tname:
            manager.note_emote_to(character_id, target_id, tname)
            manager.note_emote_from(target_id, character_id, name)
        # Self echo may note AFK so UI can show they may not notice
        if target_id is not None:
            tmeta_e = manager.get_meta(target_id)
            if tmeta_e and tmeta_e.get("afk"):
                emote_msg["target_afk"] = True
                am_e = tmeta_e.get("afk_message")
                if isinstance(am_e, str) and am_e.strip():
                    emote_msg["target_afk_message"] = am_e.strip()[:48]
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
