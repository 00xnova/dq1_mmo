"""Social emotes (extracted). Nearby AOI + directed far private delivery.

Undirected: broadcast nearby. Directed near: AOI only. Directed far: private
delivery must succeed or refund chat + restore AFK (no silent lie). Soft-grace
tracks note_emote_to/from only after successful directed path.
"""

from __future__ import annotations

from typing import Any

from game.combat_engine import combat_engine
from game.world_manager import zone_at
from network.handlers._common import (
    _afk_snap,
    _resolve_social_peer,
    _social_alias,
    peer_status_suffix,
    private_social_delivery,
    social_peer_card,
)
from network.protocol import ClientMessageType, ServerMessageType, msg
from network.websocket_manager import _is_idle, coerce_character_id, manager

EMOTE_SHORTCUTS = frozenset(
    {
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
)
EMOTE_TYPES = frozenset({ClientMessageType.EMOTE, "emote", "emotes"}) | EMOTE_SHORTCUTS
ALL_TYPES = EMOTE_TYPES

_VERBS = {
    "wave": "waves at",
    "bow": "bows to",
    "cheer": "cheers for",
    "dance": "dances with",
    "cry": "cries with",
    "laugh": "laughs with",
    "point": "points at",
    "sit": "sits with",
    "think": "thinks of",
}


async def handle(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None] | None:
    """Dispatch emote/wave/…. Returns None if not an emote message."""
    msg_type = data.get("type")
    if msg_type not in ALL_TYPES:
        return None

    allowed = set(EMOTE_SHORTCUTS)
    raw_emote = data.get("emote")
    # Only treat id/action as emote name for generic emote msgs (not /wave + to_id)
    if msg_type not in EMOTE_SHORTCUTS:
        if raw_emote is None:
            raw_emote = data.get("id")
        if raw_emote is None:
            raw_emote = data.get("action")
    # Top-level type shortcuts: {type:"wave", to:"Name"}
    if msg_type in EMOTE_SHORTCUTS and (
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
    target_name = data.get("to") or data.get("name") or data.get("target") or data.get(
        "player"
    )
    # /wave @last · @pending · reply-style directed emote
    social_mode = _social_alias(target_name, data)
    # Prefer explicit to_id / player_id. For shortcuts only, `id` is a player id
    # (generic emote uses `id` as emote name — never as target).
    raw_pid = None
    if data.get("to_id") is not None:
        raw_pid = data.get("to_id")
    elif data.get("player_id") is not None:
        raw_pid = data.get("player_id")
    elif msg_type in EMOTE_SHORTCUTS and data.get("id") is not None:
        raw_pid = data.get("id")
    target_id = (
        manager.find_id_by_player_id(raw_pid) if raw_pid is not None else None
    )
    tname: str | None = None
    # Explicit id that does not resolve → error (never fall through to undirected)
    if raw_pid is not None and target_id is None and not social_mode:
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
                    reason=empty
                    if social_mode
                    in ("pending", "share", "share_from", "emote", "emote_from")
                    else "no one to emote",
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
    was_idle = _is_idle(meta) if meta else False
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
        verb = _VERBS.get(emote, f"{emote}s at")
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
        peer = social_peer_card(manager, target_id, tname, viewer_id=character_id)
        if peer:
            suffix = peer_status_suffix(peer)
            if suffix and emote_msg.get("message"):
                # Self-only orientation; broadcast already went out without suffix
                emote_msg["message"] = str(emote_msg["message"]) + suffix
            if "nearby" in peer:
                emote_msg["nearby"] = bool(peer.get("nearby"))
            if peer.get("zone") and "peer_zone" not in emote_msg:
                emote_msg["peer_zone"] = peer["zone"]
    emote_msg["online"] = len(manager.online_ids())
    emote_msg["nearby_count"] = len(manager.ids_nearby(character_id))
    outbound.append(emote_msg)
    if was_idle:
        await manager.publish_status(character_id)
    return character_id, user_id, outbound, None
