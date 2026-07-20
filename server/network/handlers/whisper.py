"""Whisper / tell / reply (extracted). Private multiplayer chat.

Uses private_social_delivery so failed sends refund chat and restore AFK.
Validates target before allow_chat (no rate burn on offline/self/ignore).
Soft-grace note_whisper_from both sides after successful delivery.
"""

from __future__ import annotations

from typing import Any

from network.handlers._common import (
    _afk_snap,
    _resolve_social_peer,
    _social_alias,
    peer_status_suffix,
    private_social_delivery,
    sanitize_chat,
    social_peer_card,
)
from network.protocol import ClientMessageType, ServerMessageType, msg
from network.websocket_manager import _is_idle, manager

WHISPER_TYPES = frozenset(
    {
        ClientMessageType.WHISPER,
        ClientMessageType.TELL,
        ClientMessageType.REPLY,
        "whisper",
        "tell",
        "reply",
        "r",  # short alias (client usually maps /r → reply; raw type also OK)
    }
)
ALL_TYPES = WHISPER_TYPES
REPLY_TYPES = frozenset({ClientMessageType.REPLY, "reply", "r"})


async def handle(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None] | None:
    """Dispatch whisper/tell/reply. Returns None if not a whisper message."""
    msg_type = data.get("type")
    if msg_type not in ALL_TYPES:
        return None

    if character_id is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="authenticate first"))
        return character_id, user_id, outbound, None

    text = sanitize_chat(data.get("text") or data.get("message") or data.get("msg"))
    if text is None:
        outbound.append(msg(ServerMessageType.ERROR, reason="empty chat"))
        return character_id, user_id, outbound, None

    # Server-side reply / social aliases (@last · @pending)
    target_name = data.get("to") or data.get("name") or data.get("target") or data.get(
        "player"
    )
    is_reply_cmd = msg_type in REPLY_TYPES
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
    was_idle = _is_idle(meta_pre) if meta_pre else False
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
    peer = social_peer_card(manager, target_id, tname, viewer_id=character_id)
    if peer:
        suffix = peer_status_suffix(peer)
        if suffix:
            echo["message"] = f"Whisper to {tname}{suffix}."
        if "nearby" in peer:
            echo["nearby"] = bool(peer.get("nearby"))
        if peer.get("zone"):
            echo["peer_zone"] = peer["zone"]
    echo["online"] = len(manager.online_ids())
    echo["nearby_count"] = len(manager.ids_nearby(character_id))
    outbound.append(echo)
    # Target remembers us for their /r; we remember them if they reply later
    manager.note_whisper_from(target_id, character_id, name)
    manager.note_whisper_from(character_id, target_id, tname)
    if was_idle:
        await manager.publish_status(character_id)
    return character_id, user_id, outbound, None
