"""Manual AFK / busy / back (extracted). Multiplayer roster hygiene.

Toggles AFK badge, optional reason, nearby system notices on flip, and self
ack with census fields so soft reconnect / peeks stay consistent.
"""

from __future__ import annotations

from typing import Any

from game.combat_engine import combat_engine
from game.world_manager import zone_at
from network.protocol import ServerMessageType, msg
from network.websocket_manager import _is_idle, manager

AFK_TYPES = frozenset({"afk", "away", "busy", "back"})
ALL_TYPES = AFK_TYPES


def _zone_of_meta(meta: dict[str, Any] | None) -> str | None:
    if not meta:
        return None
    try:
        z = zone_at(int(meta["x"]), int(meta["y"]))
        return z if z in ("town", "field", "dungeon") else None
    except Exception:
        return None


async def handle(
    character_id: int | None,
    user_id: int | None,
    data: dict[str, Any],
    outbound: list[dict],
) -> tuple[int | None, int | None, list[dict], dict | None] | None:
    """Dispatch afk/away/busy/back. Returns None if not an AFK message."""
    msg_type = data.get("type")
    if msg_type not in ALL_TYPES:
        return None

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
        afk_msg_arg = raw_afk_text if raw_afk_text else None
    if not manager.set_afk(character_id, want_afk, message=afk_msg_arg):
        outbound.append(msg(ServerMessageType.ERROR, reason="not online"))
        return character_id, user_id, outbound, None
    if not want_afk:
        manager.touch(character_id)
    await manager.publish_status(character_id, pulse_online=True)
    meta = manager.get_meta(character_id)

    # Nearby system notice when AFK state flips (multiplayer roster hygiene)
    if want_afk != was_afk and meta is not None:
        pname = meta.get("name") or "Hero"
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
    zone = _zone_of_meta(meta)
    online_n = len(manager.online_ids())
    nearby_n = len(manager.ids_nearby(character_id))
    in_combat = combat_engine.is_in_combat(character_id)
    zone_bit = f" · {zone}" if zone else ""
    near_bit = f" · {nearby_n} nearby" if nearby_n else ""
    if want_afk:
        if ack_reason:
            base_msg = f"You are now AFK: {ack_reason}."
        else:
            base_msg = "You are now AFK."
    else:
        base_msg = "Welcome back."
    ack_body: dict[str, Any] = {
        "type": "afk",
        "afk": want_afk,
        "idle": _is_idle(meta) if meta else want_afk,
        "session_id": manager.session_id(character_id),
        "zone": zone,
        "online": online_n,
        "afk_count": manager.afk_count(),
        "nearby_count": nearby_n,
        "nearby_afk": manager.nearby_afk_count(character_id),
        "in_combat": in_combat,
        "message": base_msg + zone_bit + near_bit,
    }
    if ack_reason:
        ack_body["afk_message"] = ack_reason
    outbound.append(ack_body)
    return character_id, user_id, outbound, None
