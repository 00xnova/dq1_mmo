"""Poke / nudge private attention (extracted). Not a party.

Uses private_social_delivery so failed sends refund chat and restore AFK.
Echo includes near/far peer context without map coords.
"""

from __future__ import annotations

from typing import Any

from network.handlers._common import (
    _afk_snap,
    _resolve_social_peer,
    _social_alias,
    peer_status_suffix,
    private_social_delivery,
    social_peer_card,
)
from network.protocol import ServerMessageType, msg
from network.websocket_manager import _is_idle, coerce_character_id, manager

POKE_TYPES = frozenset({"poke", "nudge", "hey", "attention", "tap"})
ALL_TYPES = POKE_TYPES


async def handle(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None] | None:
    """Dispatch poke/nudge. Returns None if not a poke message."""
    msg_type = data.get("type")
    if msg_type not in ALL_TYPES:
        return None

    if character_id is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
        return character_id, user_id, outbound, None

    target_name = data.get("to") or data.get("name") or data.get("target") or data.get(
        "player"
    )
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
                    reason=(
                        empty
                        if social_mode
                        in (
                            "pending",
                            "share",
                            "share_from",
                            "emote",
                            "emote_from",
                        )
                        else "no one to poke"
                    ),
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
        if (
            not (isinstance(target_name, str) and target_name.strip())
            and raw_pid is None
            and not social_mode
        ):
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
    was_idle = _is_idle(meta_pre) if meta_pre else False
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
    peer = social_peer_card(manager, target_id, tname, viewer_id=character_id)
    suffix = peer_status_suffix(peer) if peer else ""
    poke_line = f"{name} is trying to get your attention."
    poke_msg: dict[str, Any] = {
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
    echo["message"] = f"You poked {tname}{suffix}."
    if peer:
        if "nearby" in peer:
            echo["nearby"] = bool(peer.get("nearby"))
        if peer.get("zone"):
            echo["zone"] = peer["zone"]
        if peer.get("online") is not None:
            echo["peer_online"] = bool(peer.get("online"))
    target_afk = bool((tmeta or {}).get("afk"))
    if target_afk:
        echo["target_afk"] = True
        am = (tmeta or {}).get("afk_message")
        if isinstance(am, str) and am.strip():
            echo["target_afk_message"] = am.strip()[:48]
    echo["online"] = len(manager.online_ids())
    echo["nearby_count"] = len(manager.ids_nearby(character_id))
    outbound.append(echo)
    if was_idle:
        await manager.publish_status(character_id)
    return character_id, user_id, outbound, None
